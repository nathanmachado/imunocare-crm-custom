from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

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
