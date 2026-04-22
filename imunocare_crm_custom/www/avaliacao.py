from __future__ import annotations

import frappe

from imunocare_crm_custom.api.survey import QF_TEMPLATE_NAME
from imunocare_crm_custom.utils.token import SurveyTokenError, verify_survey_token

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	token = (frappe.form_dict.get("t") or "").strip()
	context.token = token

	if not token:
		context.error = "Token ausente."
		return context

	try:
		lead = verify_survey_token(token)
	except SurveyTokenError as e:
		context.error = str(e) or "Token inválido."
		return context

	if not frappe.db.exists("CRM Lead", lead):
		context.error = "Lead não encontrado."
		return context

	if frappe.db.exists("Quality Feedback", {"crm_lead": lead}):
		context.already_submitted = True
		return context

	lead_doc = frappe.get_doc("CRM Lead", lead)
	context.lead_first_name = lead_doc.first_name or "Cliente"
	context.parameters = _template_parameters()
	return context


def _template_parameters() -> list[str]:
	if not frappe.db.exists("Quality Feedback Template", QF_TEMPLATE_NAME):
		return []
	tpl = frappe.get_doc("Quality Feedback Template", QF_TEMPLATE_NAME)
	return [p.parameter for p in tpl.parameters]
