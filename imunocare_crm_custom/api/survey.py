from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from imunocare_crm_custom.utils.token import (
	DEFAULT_EXPIRY_DAYS,
	SurveyTokenError,
	generate_survey_token,
	verify_survey_token,
)

QF_TEMPLATE_NAME = "Avaliação de Atendimento Imunocare"
RATING_MIN = 1
RATING_MAX = 5


class LeadNotInteracted(frappe.ValidationError):
	pass


class SurveyAlreadySubmitted(frappe.ValidationError):
	pass


@frappe.whitelist(methods=["POST"])
def close_lead(lead: str, send_invite: bool = True) -> dict:
	"""Encerra o atendimento do Lead. Snapshot do atendente e (opcionalmente) dispara convite.

	- Bloqueia se não há Communication nem CRM Call Log vinculado.
	- Idempotente: se já encerrado, retorna o estado atual sem reenviar convite.
	"""
	if not lead:
		frappe.throw("lead obrigatório")

	lead_doc = frappe.get_doc("CRM Lead", lead)
	if lead_doc.get("avaliacao_enviada"):
		return {
			"status": "already_closed",
			"lead": lead,
			"atendente_encerramento": lead_doc.atendente_encerramento,
			"encerramento_datetime": str(lead_doc.encerramento_datetime or ""),
		}

	if not _has_interaction(lead):
		frappe.throw(
			"Não é possível encerrar o Lead sem nenhuma interação (Communication ou Call Log).",
			exc=LeadNotInteracted,
		)

	atendente = frappe.session.user
	now = now_datetime()
	frappe.db.set_value(
		"CRM Lead",
		lead,
		{
			"atendente_encerramento": atendente,
			"encerramento_datetime": now,
			"avaliacao_enviada": 1,
			"status": "Converted" if lead_doc.status != "Converted" else lead_doc.status,
		},
		update_modified=True,
	)

	token = generate_survey_token(lead, expiry_days=DEFAULT_EXPIRY_DAYS)
	dispatched = False
	if send_invite:
		try:
			dispatched = bool(_dispatch_invite(lead_doc, token))
		except Exception:
			frappe.log_error(
				title=f"close_lead invite dispatch falhou (lead={lead})",
				message=frappe.get_traceback(),
			)
		if dispatched:
			frappe.db.set_value(
				"CRM Lead",
				lead,
				{
					"survey_invite_count": 1,
					"survey_last_invite_at": now,
				},
				update_modified=False,
			)

	return {
		"status": "closed",
		"lead": lead,
		"atendente_encerramento": atendente,
		"encerramento_datetime": str(now),
		"token": token,
		"dispatched": dispatched,
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit_feedback(token: str, ratings: str | dict, comment: str = ""):
	"""Recebe a resposta do cliente no Web Form público. Cria Quality Feedback.

	`ratings` é dict {param: int 1..5} (ou string JSON com esse conteúdo).
	`comment` é o feedback escrito opcional.
	"""
	try:
		lead = verify_survey_token(token)
	except SurveyTokenError:
		frappe.local.response["http_status_code"] = 400
		return {"error": "invalid_token"}

	if isinstance(ratings, str):
		try:
			ratings = json.loads(ratings)
		except json.JSONDecodeError:
			frappe.local.response["http_status_code"] = 400
			return {"error": "invalid_ratings"}
	if not isinstance(ratings, dict):
		frappe.local.response["http_status_code"] = 400
		return {"error": "invalid_ratings"}

	if not frappe.db.exists("CRM Lead", lead):
		frappe.local.response["http_status_code"] = 404
		return {"error": "lead_not_found"}

	if frappe.db.exists("Quality Feedback", {"crm_lead": lead}):
		frappe.local.response["http_status_code"] = 409
		return {"error": "already_submitted"}

	atendente = frappe.db.get_value("CRM Lead", lead, "atendente_encerramento")
	if not atendente:
		frappe.local.response["http_status_code"] = 400
		return {"error": "lead_not_closed"}

	allowed_params = _template_parameter_set()

	qf_doc = {
		"doctype": "Quality Feedback",
		"template": QF_TEMPLATE_NAME,
		"document_type": "User",
		"document_name": atendente,
		"crm_lead": lead,
		"comment": (comment or "").strip(),
		"parameters": [],
	}
	for param, value in ratings.items():
		try:
			rating = int(value)
		except (TypeError, ValueError):
			continue
		if not (RATING_MIN <= rating <= RATING_MAX):
			continue
		if allowed_params and str(param) not in allowed_params:
			# parâmetro fora do template é descartado silenciosamente para evitar
			# poluição do Quality Feedback com chaves arbitrárias enviadas via API
			continue
		qf_doc["parameters"].append({"parameter": str(param), "rating": str(rating)})

	if not qf_doc["parameters"]:
		frappe.local.response["http_status_code"] = 400
		return {"error": "no_valid_ratings"}

	doc = frappe.get_doc(qf_doc).insert(ignore_permissions=True)
	return {"ok": True, "feedback": doc.name}


def _template_parameter_set() -> set[str]:
	"""Retorna conjunto de nomes de parâmetro do template ativo.

	Vazio se o template não existir (não bloqueia o submit nesse caso —
	preserva o comportamento antigo de aceitar qualquer chave).
	"""
	if not frappe.db.exists("Quality Feedback Template", QF_TEMPLATE_NAME):
		return set()
	tpl = frappe.get_cached_doc("Quality Feedback Template", QF_TEMPLATE_NAME)
	return {p.parameter for p in tpl.parameters}


def _has_interaction(lead: str) -> bool:
	if frappe.db.exists(
		"Communication", {"reference_doctype": "CRM Lead", "reference_name": lead}
	):
		return True
	if frappe.db.exists(
		"CRM Call Log", {"reference_doctype": "CRM Lead", "reference_docname": lead}
	):
		return True
	return False


def _dispatch_invite(lead_doc, token: str) -> bool:
	"""Dispara convite de avaliação via WhatsApp HSM (se source_channel=WhatsApp) ou noop.

	Usa o app `frappe_whatsapp`: cria um `WhatsApp Message` Outgoing apontando
	pro template registrado em `WhatsApp Templates` (já aprovado na Meta). O
	`before_insert` do controller chama Meta API. Variáveis passadas via
	`body_param` JSON (formato {"1": valor1, "2": valor2, ...}).

	`imunocare_survey_invite_template` em `site_config.json` deve ser o nome
	do doc `WhatsApp Templates` (não o nome da Meta — ele já mapeia).
	"""
	channel = (lead_doc.get("source_channel") or "").strip()
	template_name = frappe.local.conf.get("imunocare_survey_invite_template")
	if not template_name or channel != "WhatsApp":
		return False

	to = lead_doc.get("mobile_no") or lead_doc.get("phone")
	if not to:
		return False

	base_url = (frappe.utils.get_url() or "").rstrip("/")
	link = f"{base_url}/avaliacao?t={token}"

	frappe.get_doc(
		{
			"doctype": "WhatsApp Message",
			"type": "Outgoing",
			"to": to,
			"template": template_name,
			"reference_doctype": "CRM Lead",
			"reference_name": lead_doc.name,
			"body_param": json.dumps({"1": lead_doc.first_name or "Cliente", "2": link}),
		}
	).insert(ignore_permissions=True)
	return True
