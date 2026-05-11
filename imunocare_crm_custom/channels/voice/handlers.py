from __future__ import annotations

import frappe
from twilio.twiml.voice_response import Dial, Gather, VoiceResponse

from imunocare_crm_custom.channels.base import get_or_create_lead, resolve_patient
from imunocare_crm_custom.twilio_integration.client import get_settings
from imunocare_crm_custom.utils.phone import normalize_phone

MISSED_CALL_STATUS = "Missed Call"
DIAL_TIMEOUT_SECONDS = 20
GATHER_TIMEOUT_SECONDS = 5
VOICE_LANG = "pt-BR"

VOICEMAIL_MESSAGE = (
	"Obrigado pelo contato com a Imunocare. No momento não podemos atender. "
	"Registramos sua chamada e retornaremos em breve."
)

CONSENT_PROMPT = (
	"Esta chamada pode ser gravada para fins de qualidade. "
	"Pressione 1 para consentir com a gravação ou qualquer outra tecla para continuar sem gravação."
)


def handle_inbound(payload: dict) -> str:
	"""Processa chamada recebida. Retorna TwiML."""
	call_sid = (payload.get("CallSid") or "").strip()
	if not call_sid:
		return _voicemail_twiml()

	if frappe.db.exists("CRM Call Log", call_sid):
		return _voicemail_twiml()

	from_addr = payload.get("From", "")
	phone = normalize_phone(from_addr)
	if not phone:
		return _voicemail_twiml()

	lead_name = get_or_create_lead(phone, "Voice")
	assignee = None
	patient_name = resolve_patient(phone)

	frappe.get_doc(
		{
			"doctype": "CRM Call Log",
			"id": call_sid,
			"from": phone,
			"to": payload.get("To", ""),
			"type": "Incoming",
			"status": "Ringing",
			"start_time": frappe.utils.now_datetime(),
			"telephony_medium": "Twilio",
			"medium": "Voice",
			"reference_doctype": "CRM Lead",
			"reference_docname": lead_name,
			"receiver": assignee,
			"patient": patient_name,
			"consent_recorded": 0,
		}
	).insert(ignore_permissions=True)

	agent_mobile = _agent_mobile(assignee) if assignee else None
	if not agent_mobile:
		_mark_missed_call(lead_name, call_sid)
		frappe.db.set_value("CRM Call Log", call_sid, "status", "No Answer", update_modified=False)
		return _voicemail_twiml()

	settings = get_settings()
	if settings.record_calls:
		return _consent_gather_twiml(call_sid, settings)
	return _dial_twiml(agent_mobile, record=False, caller_id=settings.voice_number or "")


def handle_consent_response(payload: dict) -> str:
	"""Webhook de resposta do IVR de consentimento. Retorna TwiML."""
	call_sid = (payload.get("CallSid") or "").strip()
	digits = (payload.get("Digits") or "").strip()
	consent = digits == "1"

	if not frappe.db.exists("CRM Call Log", call_sid):
		return _voicemail_twiml()

	frappe.db.set_value(
		"CRM Call Log", call_sid, "consent_recorded", 1 if consent else 0, update_modified=False
	)

	assignee = frappe.db.get_value("CRM Call Log", call_sid, "receiver")
	agent_mobile = _agent_mobile(assignee) if assignee else None
	if not agent_mobile:
		return _voicemail_twiml()

	settings = get_settings()
	return _dial_twiml(agent_mobile, record=consent, caller_id=settings.voice_number or "")


def _agent_mobile(user: str) -> str | None:
	if not user:
		return None
	mobile = frappe.db.get_value("User", user, "mobile_no")
	return normalize_phone(mobile) if mobile else None


def _mark_missed_call(lead_name: str, call_sid: str) -> None:
	frappe.db.set_value(
		"CRM Lead",
		lead_name,
		{"status": MISSED_CALL_STATUS},
		update_modified=False,
	)
	frappe.get_doc(
		{
			"doctype": "ToDo",
			"reference_type": "CRM Lead",
			"reference_name": lead_name,
			"description": f"Chamada perdida — retornar contato. CallSid: {call_sid}",
			"priority": "High",
			"status": "Open",
		}
	).insert(ignore_permissions=True)


def _voicemail_twiml() -> str:
	resp = VoiceResponse()
	resp.say(VOICEMAIL_MESSAGE, language=VOICE_LANG)
	resp.hangup()
	return str(resp)


def _consent_gather_twiml(call_sid: str, settings) -> str:
	base_url = (settings.webhook_base_url or "").rstrip("/")
	action = f"{base_url}/api/method/imunocare_crm_custom.api.twilio.voice_consent"
	resp = VoiceResponse()
	gather = Gather(num_digits=1, timeout=GATHER_TIMEOUT_SECONDS, action=action, method="POST")
	gather.say(CONSENT_PROMPT, language=VOICE_LANG)
	resp.append(gather)
	# Sem input → continua sem gravação
	resp.redirect(f"{action}?Digits=0", method="POST")
	return str(resp)


def _dial_twiml(agent_mobile: str, record: bool, caller_id: str) -> str:
	resp = VoiceResponse()
	dial_kwargs = {"timeout": DIAL_TIMEOUT_SECONDS}
	if caller_id:
		dial_kwargs["caller_id"] = caller_id
	if record:
		dial_kwargs["record"] = "record-from-answer"
	dial = Dial(**dial_kwargs)
	dial.number(agent_mobile)
	resp.append(dial)
	return str(resp)
