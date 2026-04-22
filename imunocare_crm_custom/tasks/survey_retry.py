from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime

from imunocare_crm_custom.utils.token import DEFAULT_EXPIRY_DAYS, generate_survey_token

MAX_SURVEY_INVITES = 2
RETRY_INTERVAL_HOURS = 24


def retry_survey_invites() -> dict:
	"""Reenvia convite de avaliação para leads encerrados sem resposta.

	Regras:
	- avaliacao_enviada = 1 (já encerrado)
	- Não há Quality Feedback vinculado
	- survey_invite_count < 2
	- survey_last_invite_at <= now - 24h (ou NULL)
	- Usa send_template via _dispatch_invite (que já respeita HSM)
	"""
	cutoff = add_to_date(now_datetime(), hours=-RETRY_INTERVAL_HOURS)
	candidates = frappe.db.sql(
		"""
		SELECT l.name
		FROM `tabCRM Lead` l
		LEFT JOIN `tabQuality Feedback` qf ON qf.crm_lead = l.name
		WHERE l.avaliacao_enviada = 1
		  AND qf.name IS NULL
		  AND COALESCE(l.survey_invite_count, 0) < %(max)s
		  AND (l.survey_last_invite_at IS NULL OR l.survey_last_invite_at <= %(cutoff)s)
		""",
		{"max": MAX_SURVEY_INVITES, "cutoff": cutoff},
		as_dict=True,
	)

	resent = 0
	skipped = 0
	errors = 0
	for row in candidates:
		try:
			if _retry_one(row["name"]):
				resent += 1
			else:
				skipped += 1
		except Exception:
			errors += 1
			frappe.log_error(
				title=f"retry_survey_invites falhou (lead={row['name']})",
				message=frappe.get_traceback(),
			)
	return {
		"scanned": len(candidates),
		"resent": resent,
		"skipped": skipped,
		"errors": errors,
	}


def _retry_one(lead: str) -> bool:
	from imunocare_crm_custom.api.survey import _dispatch_invite

	lead_doc = frappe.get_doc("CRM Lead", lead)
	token = generate_survey_token(lead, expiry_days=DEFAULT_EXPIRY_DAYS)
	if not _dispatch_invite(lead_doc, token):
		return False

	count = (lead_doc.get("survey_invite_count") or 0) + 1
	frappe.db.set_value(
		"CRM Lead",
		lead,
		{
			"survey_invite_count": count,
			"survey_last_invite_at": now_datetime(),
		},
		update_modified=False,
	)
	return True
