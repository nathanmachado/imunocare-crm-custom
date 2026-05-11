from __future__ import annotations

import frappe

from imunocare_crm_custom.utils.phone import normalize_phone


def before_insert(doc, method=None) -> None:
	"""Liga WhatsApp Message inbound a um CRM Lead usando normalização BR.

	O `frappe_whatsapp` upstream insere a mensagem sem `reference_doctype`/
	`reference_name`. A Meta WABA envia o `from` no formato `553491911881`
	(sem o '9' inicial obrigatório de celular BR), o que impede match exato
	com `CRM Lead.mobile_no` (`+5534991911881`). Aqui aplicamos `normalize_phone`
	(que já trata a regra ANATEL) antes do lookup.
	"""
	if doc.get("type") != "Incoming":
		return
	if doc.get("reference_doctype"):
		return

	raw_from = doc.get("from")
	if not raw_from:
		return

	e164 = normalize_phone(raw_from)
	if not e164:
		return

	lead = frappe.db.get_value("CRM Lead", {"mobile_no": e164}, "name") or frappe.db.get_value(
		"CRM Lead", {"phone": e164}, "name"
	)
	if lead:
		doc.reference_doctype = "CRM Lead"
		doc.reference_name = lead
