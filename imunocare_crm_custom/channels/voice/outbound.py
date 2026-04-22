from __future__ import annotations

import frappe
from twilio.twiml.voice_response import Dial, VoiceResponse

from imunocare_crm_custom.channels.base import resolve_patient
from imunocare_crm_custom.twilio_integration.client import get_client, get_settings
from imunocare_crm_custom.utils.phone import normalize_phone

DIAL_TIMEOUT_SECONDS = 30


class VoiceOutboundError(frappe.ValidationError):
	pass


def start_call(lead: str, agent: str | None = None) -> dict:
	"""Inicia chamada outbound em modo bridge. Retorna {call_sid, call_log}."""
	lead_doc = frappe.get_doc("CRM Lead", lead)
	to_phone = normalize_phone(lead_doc.mobile_no or lead_doc.phone or "")
	if not to_phone:
		frappe.throw(
			f"Lead {lead} não possui telefone válido.", exc=VoiceOutboundError
		)

	agent_user = agent or frappe.session.user
	agent_mobile = _agent_mobile(agent_user)
	if not agent_mobile:
		frappe.throw(
			f"Atendente {agent_user} não possui mobile_no configurado.",
			exc=VoiceOutboundError,
		)

	settings = get_settings()
	if not settings.voice_number:
		frappe.throw("Twilio Settings: voice_number não configurado.", exc=VoiceOutboundError)
	base = (settings.webhook_base_url or "").rstrip("/")
	if not base:
		frappe.throw(
			"Twilio Settings: webhook_base_url não configurado.",
			exc=VoiceOutboundError,
		)

	bridge_url = f"{base}/api/method/imunocare_crm_custom.api.twilio.voice_bridge"
	status_url = f"{base}/api/method/imunocare_crm_custom.api.twilio.voice_status"

	client = get_client()
	call = client.calls.create(
		to=agent_mobile,
		from_=settings.voice_number,
		url=bridge_url,
		method="POST",
		status_callback=status_url,
		status_callback_event=["initiated", "ringing", "answered", "completed"],
		status_callback_method="POST",
	)

	call_log = frappe.get_doc(
		{
			"doctype": "CRM Call Log",
			"id": call.sid,
			"from": settings.voice_number,
			"to": to_phone,
			"type": "Outgoing",
			"status": "Initiated",
			"start_time": frappe.utils.now_datetime(),
			"telephony_medium": "Twilio",
			"medium": "Voice",
			"reference_doctype": "CRM Lead",
			"reference_docname": lead,
			"caller": agent_user,
			"receiver": agent_user,
			"patient": resolve_patient(to_phone),
			"consent_recorded": 1 if _prior_consent(to_phone) else 0,
		}
	).insert(ignore_permissions=True)

	return {"call_sid": call.sid, "call_log": call_log.name}


def handle_bridge(payload: dict) -> str:
	"""TwiML invocado quando atendente atende. Retorna <Dial> do cliente."""
	call_sid = (payload.get("CallSid") or "").strip()
	if not call_sid or not frappe.db.exists("CRM Call Log", call_sid):
		return _hangup_twiml()

	log = frappe.db.get_value(
		"CRM Call Log", call_sid, ["to", "consent_recorded"], as_dict=True
	)
	to_phone = log.to if log else ""
	if not to_phone:
		return _hangup_twiml()

	settings = get_settings()
	record = bool(settings.record_calls and (log.consent_recorded or _prior_consent(to_phone)))

	resp = VoiceResponse()
	dial_kwargs = {"timeout": DIAL_TIMEOUT_SECONDS, "caller_id": settings.voice_number or ""}
	if record:
		dial_kwargs["record"] = "record-from-answer"
		frappe.db.set_value(
			"CRM Call Log", call_sid, "consent_recorded", 1, update_modified=False
		)
	dial = Dial(**dial_kwargs)
	dial.number(to_phone)
	resp.append(dial)
	return str(resp)


def handle_status(payload: dict) -> None:
	"""Atualiza CRM Call Log a partir do status callback."""
	call_sid = (payload.get("CallSid") or "").strip()
	if not call_sid or not frappe.db.exists("CRM Call Log", call_sid):
		return

	call_status = (payload.get("CallStatus") or "").strip()
	updates: dict = {}
	mapped = _map_status(call_status)
	if mapped:
		updates["status"] = mapped

	duration = payload.get("CallDuration")
	if duration:
		try:
			updates["duration"] = int(duration)
		except (TypeError, ValueError):
			pass

	recording_url = payload.get("RecordingUrl") or payload.get("RecordingUrl0")
	if recording_url:
		updates["recording_url"] = recording_url

	if mapped == "Completed" or call_status in ("completed", "failed", "busy", "no-answer", "canceled"):
		updates["end_time"] = frappe.utils.now_datetime()

	if updates:
		frappe.db.set_value("CRM Call Log", call_sid, updates, update_modified=False)


STATUS_MAP = {
	"initiated": "Initiated",
	"queued": "Queued",
	"ringing": "Ringing",
	"in-progress": "In Progress",
	"completed": "Completed",
	"busy": "Busy",
	"failed": "Failed",
	"no-answer": "No Answer",
	"canceled": "Canceled",
}


def _map_status(raw: str) -> str | None:
	return STATUS_MAP.get((raw or "").lower())


def _agent_mobile(user: str) -> str | None:
	if not user:
		return None
	mobile = frappe.db.get_value("User", user, "mobile_no")
	return normalize_phone(mobile) if mobile else None


def _prior_consent(phone: str) -> bool:
	return bool(
		frappe.db.exists(
			"CRM Call Log", {"from": phone, "consent_recorded": 1}
		)
		or frappe.db.exists("CRM Call Log", {"to": phone, "consent_recorded": 1})
	)


def _hangup_twiml() -> str:
	resp = VoiceResponse()
	resp.hangup()
	return str(resp)
