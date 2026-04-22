from __future__ import annotations

import json

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from imunocare_crm_custom.twilio_integration.client import get_client, get_settings
from imunocare_crm_custom.utils.phone import normalize_phone, to_whatsapp_addr

WINDOW_HOURS = 24


class WhatsAppWindowClosed(frappe.ValidationError):
	pass


class WhatsAppTemplateNotApproved(frappe.ValidationError):
	pass


def send_free_text(lead: str, body: str) -> str:
	"""Envia texto livre via WhatsApp. Exige janela 24h aberta.

	Retorna o `name` do Communication criado.
	"""
	if not body or not body.strip():
		frappe.throw("Corpo da mensagem vazio.")

	lead_doc = frappe.get_doc("CRM Lead", lead)
	to_phone = normalize_phone(lead_doc.mobile_no or lead_doc.phone or "")
	if not to_phone:
		frappe.throw(f"Lead {lead} não possui telefone válido.")

	if not is_within_24h_window(to_phone):
		frappe.throw(
			"Janela de 24h fechada: use um Message Template aprovado para contatar este Lead.",
			exc=WhatsAppWindowClosed,
		)

	settings = get_settings()
	if not settings.whatsapp_sender:
		frappe.throw("Twilio Settings: whatsapp_sender não configurado.")

	client = get_client()
	msg = client.messages.create(
		from_=to_whatsapp_addr(settings.whatsapp_sender),
		to=to_whatsapp_addr(to_phone),
		body=body,
		status_callback=_status_callback_url(settings),
	)

	return _record_outbound(
		lead=lead,
		sid=msg.sid,
		from_addr=settings.whatsapp_sender,
		to_addr=to_phone,
		body=body,
		template=None,
	)


def send_template(lead: str, template: str, variables: dict | None = None) -> str:
	"""Envia Message Template (HSM) via Twilio Content API. Sempre permitido.

	Retorna o `name` do Communication criado.
	"""
	tpl = frappe.get_doc("Message Template", template)
	if not tpl.twilio_content_sid:
		frappe.throw(f"Message Template '{template}' não tem Twilio Content SID.")
	if tpl.approval_status != "Approved":
		frappe.throw(
			f"Message Template '{template}' não está aprovado (status: {tpl.approval_status}).",
			exc=WhatsAppTemplateNotApproved,
		)

	lead_doc = frappe.get_doc("CRM Lead", lead)
	to_phone = normalize_phone(lead_doc.mobile_no or lead_doc.phone or "")
	if not to_phone:
		frappe.throw(f"Lead {lead} não possui telefone válido.")

	settings = get_settings()
	if not settings.whatsapp_sender:
		frappe.throw("Twilio Settings: whatsapp_sender não configurado.")

	client = get_client()
	content_variables = json.dumps(variables or {}, ensure_ascii=False)
	msg = client.messages.create(
		from_=to_whatsapp_addr(settings.whatsapp_sender),
		to=to_whatsapp_addr(to_phone),
		content_sid=tpl.twilio_content_sid,
		content_variables=content_variables,
		status_callback=_status_callback_url(settings),
	)

	body_preview = _render_body_preview(tpl.body, variables)
	return _record_outbound(
		lead=lead,
		sid=msg.sid,
		from_addr=settings.whatsapp_sender,
		to_addr=to_phone,
		body=body_preview,
		template=tpl.name,
	)


def is_within_24h_window(phone: str) -> bool:
	"""Retorna True se houver Communication inbound do `phone` nas últimas 24h."""
	cutoff = add_to_date(now_datetime(), hours=-WINDOW_HOURS)
	last = frappe.db.get_all(
		"Communication",
		filters={
			"communication_medium": "WhatsApp",
			"whatsapp_direction": "inbound",
			"whatsapp_from": ("like", f"%{phone}%"),
			"creation": (">=", cutoff),
		},
		fields=["name"],
		order_by="creation desc",
		limit=1,
	)
	return bool(last)


def _record_outbound(
	*,
	lead: str,
	sid: str,
	from_addr: str,
	to_addr: str,
	body: str,
	template: str | None,
) -> str:
	existing = frappe.db.get_value("Communication", {"twilio_message_sid": sid})
	if existing:
		return existing

	comm = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "WhatsApp",
			"sent_or_received": "Sent",
			"content": body,
			"reference_doctype": "CRM Lead",
			"reference_name": lead,
			"status": "Linked",
			"twilio_message_sid": sid,
			"whatsapp_direction": "outbound",
			"whatsapp_status": "queued",
			"whatsapp_from": from_addr,
			"whatsapp_to": to_addr,
		}
	)
	comm.insert(ignore_permissions=True)

	frappe.db.set_value(
		"CRM Lead", lead, "last_contact_at", now_datetime(), update_modified=False
	)
	return comm.name


def _render_body_preview(template_body: str, variables: dict | None) -> str:
	if not variables:
		return template_body
	rendered = template_body
	for k, v in variables.items():
		rendered = rendered.replace("{{" + str(k) + "}}", str(v))
	return rendered


def _status_callback_url(settings) -> str | None:
	base = (settings.webhook_base_url or "").rstrip("/")
	if not base:
		return None
	return f"{base}/api/method/imunocare_crm_custom.api.twilio.message_status"


def update_status_from_callback(sid: str, status: str) -> str | None:
	"""Atualiza whatsapp_status de Communication via MessageSid. Retorna o name ou None."""
	if not sid or not status:
		return None
	comm_name = frappe.db.get_value("Communication", {"twilio_message_sid": sid})
	if not comm_name:
		return None
	frappe.db.set_value(
		"Communication", comm_name, "whatsapp_status", status, update_modified=False
	)
	return comm_name
