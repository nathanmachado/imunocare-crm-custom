from __future__ import annotations

import json

import frappe

from imunocare_crm_custom.channels.whatsapp import sender as whatsapp_sender
from imunocare_crm_custom.utils.phone import normalize_phone


@frappe.whitelist()
def whatsapp_window_status(lead: str) -> dict:
	"""Retorna estado da janela 24h do Lead e lista de templates aprovados.

	Resposta:
		{
			"lead": "<name>",
			"phone": "<E.164 ou ''>",
			"open": bool,
			"templates": [
				{"name": ..., "twilio_content_sid": ..., "body": ...},
				...
			]
		}
	"""
	if not lead:
		frappe.throw("lead obrigatório")

	lead_doc = frappe.get_doc("CRM Lead", lead)
	phone = normalize_phone(lead_doc.mobile_no or lead_doc.phone or "")
	open_window = bool(phone) and whatsapp_sender.is_within_24h_window(phone)

	templates = frappe.get_all(
		"Message Template",
		filters={"approval_status": "Approved"},
		fields=["name", "twilio_content_sid", "body"],
		order_by="name asc",
	)

	return {
		"lead": lead,
		"phone": phone,
		"open": open_window,
		"templates": templates,
	}


@frappe.whitelist(methods=["POST"])
def send_whatsapp_from_lead(
	lead: str,
	body: str | None = None,
	template: str | None = None,
	variables: str | dict | None = None,
) -> dict:
	"""Despacha WhatsApp a partir do Lead, roteando para free_text ou template.

	- Se `template` informado: usa `send_template` (sempre permitido).
	- Caso contrário: usa `send_free_text` (exige janela 24h aberta).
	"""
	if not lead:
		frappe.throw("lead obrigatório")

	if template:
		vars_dict = _parse_variables(variables)
		name = whatsapp_sender.send_template(lead=lead, template=template, variables=vars_dict)
		return {"ok": True, "communication": name, "mode": "template"}

	text = (body or "").strip()
	if not text:
		frappe.throw("Informe `body` ou `template`.")

	name = whatsapp_sender.send_free_text(lead=lead, body=text)
	return {"ok": True, "communication": name, "mode": "free_text"}


def _parse_variables(variables: str | dict | None) -> dict:
	if variables is None or variables == "":
		return {}
	if isinstance(variables, dict):
		return variables
	if isinstance(variables, str):
		try:
			parsed = json.loads(variables)
		except json.JSONDecodeError:
			frappe.throw("`variables` deve ser JSON válido.")
		if not isinstance(parsed, dict):
			frappe.throw("`variables` deve ser objeto JSON (chave→valor).")
		return parsed
	frappe.throw("`variables` inválido.")
	return {}
