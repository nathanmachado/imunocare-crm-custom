from __future__ import annotations

import mimetypes

import frappe
import requests

from imunocare_crm_custom.channels.base import get_or_create_lead
from imunocare_crm_custom.twilio_integration.client import get_settings
from imunocare_crm_custom.utils.phone import normalize_phone

MEDIA_DOWNLOAD_TIMEOUT = 30


def handle_inbound(payload: dict) -> str | None:
	"""Processa WhatsApp recebido: cria/reusa Lead e registra Communication com mídia.

	Retorna o `name` do Communication criado (ou existente em replay). None se payload inválido.
	"""
	sid = (payload.get("MessageSid") or "").strip()
	if not sid:
		return None

	existing = frappe.db.get_value("Communication", {"twilio_message_sid": sid})
	if existing:
		return existing

	from_addr = payload.get("From", "")
	phone = normalize_phone(from_addr)
	if not phone:
		frappe.log_error(title="WhatsApp inbound: telefone inválido", message=frappe.as_json(payload))
		return None

	display_name = (payload.get("ProfileName") or "").strip() or None
	body = payload.get("Body") or ""

	lead_name = get_or_create_lead(phone, "WhatsApp", display_name=display_name)

	comm = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "WhatsApp",
			"sent_or_received": "Received",
			"sender_full_name": display_name or phone,
			"content": body,
			"reference_doctype": "CRM Lead",
			"reference_name": lead_name,
			"status": "Open",
			"twilio_message_sid": sid,
			"whatsapp_direction": "inbound",
			"whatsapp_status": "received",
			"whatsapp_from": from_addr,
			"whatsapp_to": payload.get("To", ""),
		}
	)
	comm.insert(ignore_permissions=True)

	num_media = _parse_int(payload.get("NumMedia"))
	for i in range(num_media):
		media_url = payload.get(f"MediaUrl{i}")
		if not media_url:
			continue
		content_type = payload.get(f"MediaContentType{i}", "application/octet-stream")
		try:
			_download_and_attach_media(
				comm_name=comm.name,
				url=media_url,
				content_type=content_type,
				index=i,
				sid=sid,
			)
		except Exception:
			frappe.log_error(
				title=f"WhatsApp media download falhou (sid={sid}, idx={i})",
				message=frappe.get_traceback(),
			)

	return comm.name


def _parse_int(value) -> int:
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


def _download_and_attach_media(
	*, comm_name: str, url: str, content_type: str, index: int, sid: str
) -> None:
	settings = get_settings()
	auth_token = settings.get_password("auth_token", raise_exception=True)
	resp = requests.get(
		url,
		auth=(settings.account_sid, auth_token),
		timeout=MEDIA_DOWNLOAD_TIMEOUT,
		allow_redirects=True,
	)
	resp.raise_for_status()

	ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
	filename = f"{sid}_{index}{ext}"

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"attached_to_doctype": "Communication",
			"attached_to_name": comm_name,
			"content": resp.content,
			"is_private": 1,
		}
	)
	file_doc.save(ignore_permissions=True)
