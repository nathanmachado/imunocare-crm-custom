from __future__ import annotations

import frappe

from imunocare_crm_custom.channels.base import get_or_create_lead


def before_insert(doc, method=None) -> None:
	"""Liga WhatsApp Message inbound a um CRM Lead.

	Quando a mensagem entra pelo webhook do `frappe_whatsapp`, ela vem sem
	`reference_doctype`/`reference_name`. A Meta WABA envia o `from` no
	formato `553491911881` (sem o '9' inicial obrigatório de celular BR),
	o que impede match exato com `CRM Lead.mobile_no` (`+5534991911881`).

	Reutilizamos `get_or_create_lead` (channels/base.py) que:
	1. Normaliza o número (regra ANATEL '9' BR + E.164)
	2. Resolve Patient pelo número (se existir)
	3. Garante um Contact
	4. Busca Lead aberto pelo número/paciente; se não existir, cria um novo
	   com `source_channel="WhatsApp"` + `first_name` do `profile_name` Meta.

	Assim, cada conversa WhatsApp recém-iniciada vira um Lead pronto no CRM,
	já vinculado ao Patient quando o número bate com um cadastro Healthcare.
	"""
	if doc.get("type") != "Incoming":
		return
	if doc.get("reference_doctype"):
		return

	raw_from = doc.get("from")
	if not raw_from:
		return

	try:
		lead = get_or_create_lead(
			phone=raw_from,
			channel="WhatsApp",
			display_name=doc.get("profile_name") or None,
		)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			"Imunocare: falha ao resolver/criar Lead a partir de WhatsApp inbound",
		)
		return

	doc.reference_doctype = "CRM Lead"
	doc.reference_name = lead


def after_insert(doc, method=None) -> None:
	"""Re-emite o evento socketio `whatsapp_message` após o commit.

	O `crm.api.whatsapp.on_update` do CRM upstream chama `publish_realtime`
	sem `after_commit=True`, então emite ANTES do commit. O frontend recebe
	o evento, dispara `whatsappMessages.reload()`, mas a query SELECT no DB
	ainda não enxerga o registro novo. Aqui re-emitimos o mesmo evento com
	`after_commit=True` para garantir que o reload do frontend acontece com
	o registro já visível no banco — atualização realtime sem F5.
	"""
	if not doc.get("reference_doctype") or not doc.get("reference_name"):
		return
	frappe.publish_realtime(
		"whatsapp_message",
		{
			"reference_doctype": doc.reference_doctype,
			"reference_name": doc.reference_name,
		},
		after_commit=True,
	)
