from __future__ import annotations

import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

COMMUNICATION_CUSTOM_FIELDS: dict[str, list[dict]] = {}

COMMUNICATION_MEDIUM_OPTIONS = "\nEmail\nChat\nPhone\nSMS\nEvent\nMeeting\nVisit\nWhatsApp\nOther"

QUALITY_FEEDBACK_CUSTOM_FIELDS = {
	"Quality Feedback": [
		{
			"fieldname": "crm_lead",
			"fieldtype": "Link",
			"label": "CRM Lead",
			"options": "CRM Lead",
			"insert_after": "document_name",
			"description": "Lead associado à avaliação",
		},
		{
			"fieldname": "comment",
			"fieldtype": "Long Text",
			"label": "Comentário do cliente",
			"insert_after": "parameters",
			"description": "Feedback escrito opcional",
		},
	]
}


CRM_CALL_LOG_CUSTOM_FIELDS = {
	"CRM Call Log": [
		{
			"fieldname": "patient",
			"fieldtype": "Link",
			"label": "Paciente",
			"options": "Patient",
			"insert_after": "reference_docname",
			"read_only": 1,
		},
	]
}

CRM_LEAD_STATUSES = [
	{
		"doctype": "CRM Lead Status",
		"name": "Missed Call",
		"lead_status": "Missed Call",
		"type": "Open",
		"color": "yellow",
	},
]

QF_TEMPLATE_NAME = "Avaliação de Atendimento Imunocare"
QF_TEMPLATE_PARAMETERS = [
	"Canal",
	"Cordialidade",
	"Resolução",
	"Tempo de resposta",
]

CRM_LEAD_FORM_SCRIPT_NAME = "Imunocare CRM Lead Actions"
CRM_LEAD_FORM_SCRIPT_PATH = ("crm_form_scripts", "crm_lead_actions.js")


CRM_LEAD_CUSTOM_FIELDS = {
	"CRM Lead": [
		{
			"fieldname": "imunocare_channel_section",
			"fieldtype": "Section Break",
			"label": "Imunocare — Canal de Origem",
			"insert_after": "source",
			"collapsible": 1,
		},
		{
			"fieldname": "source_channel",
			"fieldtype": "Select",
			"label": "Canal de Origem (Imunocare)",
			"options": "\nWhatsApp\nVoice",
			"insert_after": "imunocare_channel_section",
			"in_standard_filter": 1,
		},
		{
			"fieldname": "patient",
			"fieldtype": "Link",
			"label": "Paciente",
			"options": "Patient",
			"insert_after": "source_channel",
			"description": "Vinculado quando o contato já existe como paciente no Healthcare",
		},
		{
			"fieldname": "column_break_imunocare_contacts",
			"fieldtype": "Column Break",
			"insert_after": "patient",
		},
		{
			"fieldname": "first_contact_at",
			"fieldtype": "Datetime",
			"label": "Primeiro Contato",
			"insert_after": "column_break_imunocare_contacts",
			"read_only": 1,
		},
		{
			"fieldname": "last_contact_at",
			"fieldtype": "Datetime",
			"label": "Último Contato",
			"insert_after": "first_contact_at",
			"read_only": 1,
		},
		{
			"fieldname": "avaliacao_enviada",
			"fieldtype": "Check",
			"label": "Avaliação Enviada",
			"insert_after": "last_contact_at",
			"read_only": 1,
			"default": "0",
		},
		{
			"fieldname": "atendente_encerramento",
			"fieldtype": "Link",
			"label": "Atendente de Encerramento",
			"options": "User",
			"insert_after": "avaliacao_enviada",
			"read_only": 1,
			"description": "Snapshot do atendente no momento do encerramento",
		},
		{
			"fieldname": "encerramento_datetime",
			"fieldtype": "Datetime",
			"label": "Encerrado em",
			"insert_after": "atendente_encerramento",
			"read_only": 1,
		},
		{
			"fieldname": "survey_invite_count",
			"fieldtype": "Int",
			"label": "Tentativas de Convite",
			"insert_after": "encerramento_datetime",
			"read_only": 1,
			"default": "0",
			"description": "Quantas vezes o convite de avaliação foi disparado (máx 2)",
		},
		{
			"fieldname": "survey_last_invite_at",
			"fieldtype": "Datetime",
			"label": "Último Convite Enviado em",
			"insert_after": "survey_invite_count",
			"read_only": 1,
		},
		{
			"fieldname": "inativo_tagged_at",
			"fieldtype": "Datetime",
			"label": "Marcado como Inativo em",
			"insert_after": "survey_last_invite_at",
			"read_only": 1,
		},
	]
}


def install_custom_fields() -> None:
	create_custom_fields(CRM_LEAD_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(COMMUNICATION_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(CRM_CALL_LOG_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(QUALITY_FEEDBACK_CUSTOM_FIELDS, ignore_validate=True)
	make_property_setter(
		"Communication",
		"communication_medium",
		"options",
		COMMUNICATION_MEDIUM_OPTIONS,
		"Text",
		validate_fields_for_doctype=False,
	)
	_ensure_crm_lead_statuses()
	_ensure_qf_template()
	_ensure_crm_lead_form_script()


def _ensure_crm_lead_statuses() -> None:
	for status in CRM_LEAD_STATUSES:
		if not frappe.db.exists("CRM Lead Status", status["lead_status"]):
			frappe.get_doc(status).insert(ignore_permissions=True, ignore_if_duplicate=True)


def _ensure_qf_template() -> None:
	if frappe.db.exists("Quality Feedback Template", QF_TEMPLATE_NAME):
		return
	frappe.get_doc(
		{
			"doctype": "Quality Feedback Template",
			"template": QF_TEMPLATE_NAME,
			"parameters": [{"parameter": p} for p in QF_TEMPLATE_PARAMETERS],
		}
	).insert(ignore_permissions=True, ignore_if_duplicate=True)


def _ensure_crm_lead_form_script() -> None:
	"""Registra o CRM Form Script que injeta 3 ações no header do CRM Lead no Portal.

	Fonte do script: `crm_form_scripts/crm_lead_actions.js`. Atualiza o doc se o
	conteúdo divergir, para que mudanças no arquivo sejam aplicadas no próximo
	`bench migrate`.
	"""
	if not frappe.db.exists("DocType", "CRM Form Script"):
		return
	app_path = frappe.get_app_path("imunocare_crm_custom")
	script_path = os.path.join(app_path, *CRM_LEAD_FORM_SCRIPT_PATH)
	with open(script_path, encoding="utf-8") as fh:
		script_body = fh.read()

	payload = {
		"doctype": "CRM Form Script",
		"name": CRM_LEAD_FORM_SCRIPT_NAME,
		"dt": "CRM Lead",
		"view": "Form",
		"enabled": 1,
		"is_standard": 0,
		"script": script_body,
	}

	if frappe.db.exists("CRM Form Script", CRM_LEAD_FORM_SCRIPT_NAME):
		doc = frappe.get_doc("CRM Form Script", CRM_LEAD_FORM_SCRIPT_NAME)
		dirty = False
		for key in ("dt", "view", "enabled", "is_standard", "script"):
			if doc.get(key) != payload[key]:
				doc.set(key, payload[key])
				dirty = True
		if dirty:
			doc.save(ignore_permissions=True)
	else:
		frappe.get_doc(payload).insert(ignore_permissions=True, ignore_if_duplicate=True)


