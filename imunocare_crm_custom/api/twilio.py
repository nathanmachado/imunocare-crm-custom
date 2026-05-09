from __future__ import annotations

import json

import frappe
from twilio.request_validator import RequestValidator
from werkzeug.wrappers import Response

from imunocare_crm_custom.twilio_integration.client import get_settings

WHATSAPP_TWIML_EMPTY = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
VOICE_TWIML_HANGUP = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook():
	request = frappe.request
	params = dict(frappe.form_dict)
	params.pop("cmd", None)

	channel = _detect_channel(params)
	sid = params.get("MessageSid") or params.get("CallSid") or ""

	url = _full_url(request)
	signature = request.headers.get("X-Twilio-Signature", "")
	signature_valid = _validate_signature(url, params, signature)

	if not signature_valid:
		frappe.local.response["http_status_code"] = 403
		return {"error": "invalid_signature"}

	if not sid:
		frappe.local.response["http_status_code"] = 400
		return {"error": "missing_sid"}

	if _is_replay(sid):
		return _respond_for_channel(channel)

	_log_event(sid=sid, channel=channel, url=url, params=params, signature_valid=True)

	try:
		if channel == "WhatsApp":
			_handle_whatsapp(params)
		elif channel == "Voice":
			twiml = _handle_voice(params)
			frappe.db.set_value(
				"Twilio Webhook Event", sid, "processed", 1, update_modified=False
			)
			return _set_xml_response(twiml)
		frappe.db.set_value(
			"Twilio Webhook Event", sid, "processed", 1, update_modified=False
		)
	except Exception as e:
		frappe.log_error(title=f"Twilio webhook processing failed ({channel})", message=frappe.get_traceback())
		frappe.db.set_value(
			"Twilio Webhook Event", sid, "processing_error", str(e)[:500], update_modified=False
		)

	return _respond_for_channel(channel)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def message_status():
	"""Webhook de status callback para mensagens WhatsApp/SMS outbound (MVP-06)."""
	from imunocare_crm_custom.channels.whatsapp.sender import update_status_from_callback

	request = frappe.request
	params = dict(frappe.form_dict)
	params.pop("cmd", None)

	url = _full_url(request)
	signature = request.headers.get("X-Twilio-Signature", "")
	if not _validate_signature(url, params, signature):
		frappe.local.response["http_status_code"] = 403
		return {"error": "invalid_signature"}

	sid = (params.get("MessageSid") or "").strip()
	status = (params.get("MessageStatus") or "").strip().lower()
	if not sid or not status:
		frappe.local.response["http_status_code"] = 400
		return {"error": "missing_sid_or_status"}

	try:
		update_status_from_callback(sid, status)
	except Exception:
		frappe.log_error(
			title=f"Twilio message_status processing failed (sid={sid})",
			message=frappe.get_traceback(),
		)

	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def voice_start(lead: str, agent: str | None = None):
	"""Inicia click-to-call para o Lead (autenticado, MVP-07)."""
	from imunocare_crm_custom.channels.voice.outbound import start_call

	return start_call(lead=lead, agent=agent)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def voice_bridge():
	"""TwiML invocado quando o atendente atende o outbound call (MVP-07)."""
	from imunocare_crm_custom.channels.voice.outbound import handle_bridge

	request = frappe.request
	params = dict(frappe.form_dict)
	params.pop("cmd", None)

	url = _full_url(request)
	signature = request.headers.get("X-Twilio-Signature", "")
	if not _validate_signature(url, params, signature):
		frappe.local.response["http_status_code"] = 403
		return {"error": "invalid_signature"}

	try:
		twiml = handle_bridge(params)
	except Exception:
		frappe.log_error(title="Twilio voice_bridge failed", message=frappe.get_traceback())
		return _set_xml_response(VOICE_TWIML_HANGUP)

	return _set_xml_response(twiml)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def voice_status():
	"""Status callback para chamadas outbound (MVP-07)."""
	from imunocare_crm_custom.channels.voice.outbound import handle_status

	request = frappe.request
	params = dict(frappe.form_dict)
	params.pop("cmd", None)

	url = _full_url(request)
	signature = request.headers.get("X-Twilio-Signature", "")
	if not _validate_signature(url, params, signature):
		frappe.local.response["http_status_code"] = 403
		return {"error": "invalid_signature"}

	try:
		handle_status(params)
	except Exception:
		frappe.log_error(title="Twilio voice_status failed", message=frappe.get_traceback())

	return {"ok": True}


@frappe.whitelist(methods=["GET"])
def recording_proxy(call_sid: str):
	"""Proxy autenticado para a gravação Twilio de um CRM Call Log (MVP-10).

	- Exige usuário autenticado com permissão de leitura no Call Log.
	- Busca `recording_url` gravado no Call Log e faz fetch em `https://api.twilio.com`
	  usando Basic Auth (AccountSid:AuthToken) — nunca expõe credenciais ao cliente.
	- Devolve o áudio como binary (audio/mpeg) para consumo via <audio controls>.
	"""
	import requests

	call_sid = (call_sid or "").strip()
	if not call_sid:
		frappe.throw("call_sid obrigatório")

	if not frappe.db.exists("CRM Call Log", call_sid):
		frappe.local.response["http_status_code"] = 404
		return {"error": "call_log_not_found"}

	try:
		frappe.get_doc("CRM Call Log", call_sid).check_permission("read")
	except frappe.PermissionError:
		frappe.local.response["http_status_code"] = 403
		return {"error": "forbidden"}

	recording_url = frappe.db.get_value("CRM Call Log", call_sid, "recording_url")
	if not recording_url:
		frappe.local.response["http_status_code"] = 404
		return {"error": "recording_not_available"}

	settings = get_settings()
	auth_token = settings.get_password("auth_token", raise_exception=False)
	if not settings.account_sid or not auth_token:
		frappe.local.response["http_status_code"] = 503
		return {"error": "twilio_not_configured"}

	fetch_url = recording_url if recording_url.endswith(".mp3") else f"{recording_url}.mp3"
	try:
		resp = requests.get(
			fetch_url, auth=(settings.account_sid, auth_token), timeout=30
		)
	except requests.RequestException as e:
		frappe.log_error(
			title=f"recording_proxy fetch failed (sid={call_sid})",
			message=f"{fetch_url}\n{e}",
		)
		frappe.local.response["http_status_code"] = 502
		return {"error": "upstream_fetch_failed"}

	if resp.status_code != 200:
		frappe.local.response["http_status_code"] = 502
		return {"error": "upstream_status_" + str(resp.status_code)}

	frappe.local.response.filename = f"call_{call_sid}.mp3"
	frappe.local.response.filecontent = resp.content
	frappe.local.response.type = "binary"
	frappe.local.response.headers = {"Content-Type": "audio/mpeg"}
	return


@frappe.whitelist(allow_guest=True, methods=["POST"])
def voice_consent():
	"""Webhook invocado pelo <Gather> do IVR de consentimento (MVP-05)."""
	from imunocare_crm_custom.channels.voice.handlers import handle_consent_response

	request = frappe.request
	params = dict(frappe.form_dict)
	params.pop("cmd", None)

	url = _full_url(request)
	signature = request.headers.get("X-Twilio-Signature", "")
	if not _validate_signature(url, params, signature):
		frappe.local.response["http_status_code"] = 403
		return {"error": "invalid_signature"}

	call_sid = (params.get("CallSid") or "").strip()
	if not call_sid:
		frappe.local.response["http_status_code"] = 400
		return {"error": "missing_sid"}

	try:
		twiml = handle_consent_response(params)
	except Exception as e:
		frappe.log_error(title="Twilio voice_consent failed", message=frappe.get_traceback())
		return _set_xml_response(VOICE_TWIML_HANGUP)

	return _set_xml_response(twiml)


def _detect_channel(params: dict) -> str:
	if params.get("MessageSid"):
		return "WhatsApp"
	if params.get("CallSid"):
		return "Voice"
	return "Unknown"


def _full_url(request) -> str:
	proto = request.headers.get("X-Forwarded-Proto") or request.scheme
	host = request.headers.get("X-Forwarded-Host") or request.host
	return f"{proto}://{host}{request.path}"


def _validate_signature(url: str, params: dict, signature: str) -> bool:
	if not signature:
		return False
	settings = get_settings()
	auth_token = settings.get_password("auth_token", raise_exception=False)
	if not auth_token:
		return False
	validator = RequestValidator(auth_token)
	return validator.validate(url, params, signature)


def _is_replay(sid: str) -> bool:
	return bool(frappe.db.exists("Twilio Webhook Event", sid))


def _log_event(*, sid: str, channel: str, url: str, params: dict, signature_valid: bool) -> None:
	doc = frappe.get_doc(
		{
			"doctype": "Twilio Webhook Event",
			"sid": sid,
			"channel": channel,
			"http_method": "POST",
			"received_at": frappe.utils.now_datetime(),
			"signature_valid": 1 if signature_valid else 0,
			"url": url,
			"params": json.dumps(params, ensure_ascii=False, indent=2),
		}
	)
	doc.insert(ignore_permissions=True)


def _handle_whatsapp(params: dict) -> None:
	from imunocare_crm_custom.channels.whatsapp.handlers import handle_inbound

	handle_inbound(params)


def _handle_voice(params: dict) -> str:
	from imunocare_crm_custom.channels.voice.handlers import handle_inbound

	return handle_inbound(params)


def _set_xml_response(xml: str):
	return Response(xml, mimetype="text/xml")


def _respond_for_channel(channel: str):
	if channel == "Voice":
		return _set_xml_response(VOICE_TWIML_HANGUP)
	return _set_xml_response(WHATSAPP_TWIML_EMPTY)
