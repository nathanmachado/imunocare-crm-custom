from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

COMMUNICATION_CUSTOM_FIELDS = {
	"Communication": [
		{
			"fieldname": "twilio_section",
			"fieldtype": "Section Break",
			"label": "Twilio",
			"insert_after": "references_section",
			"collapsible": 1,
		},
		{
			"fieldname": "twilio_message_sid",
			"fieldtype": "Data",
			"label": "Twilio Message SID",
			"insert_after": "twilio_section",
			"unique": 1,
			"read_only": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "whatsapp_direction",
			"fieldtype": "Select",
			"label": "WhatsApp Direction",
			"options": "\ninbound\noutbound",
			"insert_after": "twilio_message_sid",
			"read_only": 1,
		},
		{
			"fieldname": "whatsapp_status",
			"fieldtype": "Data",
			"label": "WhatsApp Status",
			"insert_after": "whatsapp_direction",
			"read_only": 1,
			"description": "queued, sent, delivered, read, failed, undelivered, received",
		},
		{
			"fieldname": "whatsapp_from",
			"fieldtype": "Data",
			"label": "WhatsApp From",
			"insert_after": "whatsapp_status",
			"read_only": 1,
		},
		{
			"fieldname": "whatsapp_to",
			"fieldtype": "Data",
			"label": "WhatsApp To",
			"insert_after": "whatsapp_from",
			"read_only": 1,
		},
	]
}

COMMUNICATION_MEDIUM_OPTIONS = "\nEmail\nChat\nPhone\nSMS\nEvent\nMeeting\nVisit\nWhatsApp\nOther"

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
		{
			"fieldname": "consent_recorded",
			"fieldtype": "Check",
			"label": "Consentimento de Gravação",
			"insert_after": "recording_url",
			"default": "0",
			"description": "Cliente autorizou gravação da chamada via IVR (LGPD)",
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

IMUNOCARE_ATTENDANT_ROLE = "Imunocare Atendente"

ASSIGNMENT_RULE_NAME = "Imunocare CRM Lead Round Robin"


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
	]
}


def install_custom_fields() -> None:
	create_custom_fields(CRM_LEAD_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(COMMUNICATION_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(CRM_CALL_LOG_CUSTOM_FIELDS, ignore_validate=True)
	make_property_setter(
		"Communication",
		"communication_medium",
		"options",
		COMMUNICATION_MEDIUM_OPTIONS,
		"Text",
		validate_fields_for_doctype=False,
	)
	_ensure_crm_lead_statuses()
	_ensure_attendant_role()
	_ensure_assignment_rule()


def _ensure_crm_lead_statuses() -> None:
	for status in CRM_LEAD_STATUSES:
		if not frappe.db.exists("CRM Lead Status", status["lead_status"]):
			frappe.get_doc(status).insert(ignore_permissions=True, ignore_if_duplicate=True)


def _ensure_attendant_role() -> None:
	if not frappe.db.exists("Role", IMUNOCARE_ATTENDANT_ROLE):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": IMUNOCARE_ATTENDANT_ROLE,
				"desk_access": 1,
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)


def _ensure_assignment_rule() -> None:
	if not frappe.db.exists("Assignment Rule", ASSIGNMENT_RULE_NAME):
		frappe.get_doc(
			{
				"doctype": "Assignment Rule",
				"name": ASSIGNMENT_RULE_NAME,
				"document_type": "CRM Lead",
				"description": "Distribui CRM Lead novo entre atendentes Imunocare via round-robin.",
				"priority": 10,
				"disabled": 1,
				"rule": "Round Robin",
				"assign_condition": 'status == "New"',
				"unassign_condition": 'status in ("Converted", "Lost", "Missed Call")',
				"assignment_days": [
					{"day": "Monday"},
					{"day": "Tuesday"},
					{"day": "Wednesday"},
					{"day": "Thursday"},
					{"day": "Friday"},
					{"day": "Saturday"},
					{"day": "Sunday"},
				],
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)
	sync_assignment_rule_users()


def sync_assignment_rule_users() -> None:
	"""Sincroniza os users do Assignment Rule com os usuários ativos que possuem o role Imunocare Atendente."""
	if not frappe.db.exists("Assignment Rule", ASSIGNMENT_RULE_NAME):
		return
	role_users = frappe.get_all(
		"Has Role",
		filters={"role": IMUNOCARE_ATTENDANT_ROLE, "parenttype": "User"},
		pluck="parent",
	)
	active = [u for u in role_users if frappe.db.get_value("User", u, "enabled")]

	rule = frappe.get_doc("Assignment Rule", ASSIGNMENT_RULE_NAME)
	current = {u.user for u in (rule.users or [])}
	desired = set(active)
	if current == desired and bool(desired) == (not rule.disabled):
		return
	rule.users = []
	for u in sorted(desired):
		rule.append("users", {"user": u})
	rule.disabled = 0 if desired else 1
	rule.save(ignore_permissions=True)
