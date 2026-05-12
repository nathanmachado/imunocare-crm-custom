"""Remove resíduos do código legacy Twilio/WhatsApp custom.

Limpa em sites já provisionados:

- Custom Fields exclusivos do canal Twilio/WhatsApp custom (Communication-*
  e CRM Call Log-consent_recorded).
- Registros remanescentes do DocType Twilio Settings (caso a pasta tenha
  sido deletada mas a tabela ainda exista no DB de sites antigos).
- Single doctype settings antigo do Twilio que pode ter ficado em
  `tabSingles`.

Idempotente: cada operação verifica existência antes de tentar deletar.
"""
from __future__ import annotations

import frappe


LEGACY_CUSTOM_FIELDS = [
	"Communication-twilio_section",
	"Communication-twilio_message_sid",
	"Communication-whatsapp_direction",
	"Communication-whatsapp_status",
	"Communication-whatsapp_from",
	"Communication-whatsapp_to",
	"CRM Call Log-consent_recorded",
]

LEGACY_DOCTYPES = [
	"Twilio Settings",
	"Twilio Webhook Event",
	"Message Template",
	"Message Template Variable",
]


def execute() -> None:
	for cf in LEGACY_CUSTOM_FIELDS:
		if frappe.db.exists("Custom Field", cf):
			frappe.delete_doc("Custom Field", cf, force=True, ignore_permissions=True)

	for dt in LEGACY_DOCTYPES:
		if frappe.db.exists("DocType", dt):
			frappe.delete_doc("DocType", dt, force=True, ignore_permissions=True)

	frappe.db.sql("DELETE FROM tabSingles WHERE doctype IN %(dts)s", {"dts": tuple(LEGACY_DOCTYPES)})
	frappe.db.commit()
