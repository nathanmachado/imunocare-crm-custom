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
	make_property_setter(
		"Communication",
		"communication_medium",
		"options",
		COMMUNICATION_MEDIUM_OPTIONS,
		"Text",
		validate_fields_for_doctype=False,
	)
