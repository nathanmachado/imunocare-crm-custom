from __future__ import annotations

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.channels.voice import outbound

PHONE_CUSTOMER = "+5511944440001"
PHONE_AGENT = "+5511933330001"
VOICE_NUMBER = "+5511888880000"
AGENT_EMAIL = "voice-outbound-agent@example.com"

TEST_ACCOUNT_SID = "ACtest00000000000000000000000000"
TEST_AUTH_TOKEN = "test_auth_token_32bytes_000000000"
TEST_WEBHOOK_BASE = "https://imunocare.vps-kinghost.net"


def _apply_settings(**kwargs):
	settings = frappe.get_single("Twilio Settings")
	for k, v in kwargs.items():
		setattr(settings, k, v)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()


def _cleanup() -> None:
	for phone in (PHONE_CUSTOMER, VOICE_NUMBER):
		for name in frappe.get_all("CRM Call Log", filters={"from": phone}, pluck="name"):
			frappe.delete_doc("CRM Call Log", name, ignore_permissions=True, force=True)
		for name in frappe.get_all("CRM Call Log", filters={"to": phone}, pluck="name"):
			frappe.delete_doc("CRM Call Log", name, ignore_permissions=True, force=True)
	for name in frappe.get_all("CRM Lead", filters={"mobile_no": PHONE_CUSTOMER}, pluck="name"):
		for todo in frappe.get_all(
			"ToDo", filters={"reference_type": "CRM Lead", "reference_name": name}, pluck="name"
		):
			frappe.delete_doc("ToDo", todo, ignore_permissions=True, force=True)
		frappe.delete_doc("CRM Lead", name, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestVoiceOutbound(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Twilio Settings")
		cls._orig = {
			"account_sid": settings.account_sid or "",
			"auth_token": settings.get_password("auth_token", raise_exception=False) or "",
			"voice_number": settings.voice_number or "",
			"webhook_base_url": settings.webhook_base_url or "",
			"record_calls": settings.record_calls or 0,
		}
		_apply_settings(
			account_sid=TEST_ACCOUNT_SID,
			auth_token=TEST_AUTH_TOKEN,
			voice_number=VOICE_NUMBER,
			webhook_base_url=TEST_WEBHOOK_BASE,
			record_calls=0,
		)
		_cleanup()
		if not frappe.db.exists("User", AGENT_EMAIL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": AGENT_EMAIL,
					"first_name": "Outbound",
					"last_name": "Agent",
					"mobile_no": PHONE_AGENT,
					"send_welcome_email": 0,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		else:
			frappe.db.set_value("User", AGENT_EMAIL, "mobile_no", PHONE_AGENT)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		if frappe.db.exists("User", AGENT_EMAIL):
			frappe.delete_doc("User", AGENT_EMAIL, ignore_permissions=True, force=True)
		_apply_settings(**cls._orig)
		super().tearDownClass()

	def setUp(self):
		_cleanup()
		_apply_settings(record_calls=0)

	def _create_lead(self) -> str:
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Outbound Test",
				"mobile_no": PHONE_CUSTOMER,
				"phone": PHONE_CUSTOMER,
				"source_channel": "Voice",
			}
		).insert(ignore_permissions=True)
		return lead.name

	def _fake_call(self, sid: str):
		call = MagicMock()
		call.sid = sid
		client = MagicMock()
		client.calls.create.return_value = call
		return client, call

	def test_start_call_creates_outbound_call_log(self):
		lead = self._create_lead()
		client, call = self._fake_call("CAout000000000000000000000000001")
		with patch.object(outbound, "get_client", return_value=client):
			result = outbound.start_call(lead=lead, agent=AGENT_EMAIL)

		self.assertEqual(result["call_sid"], call.sid)
		log = frappe.get_doc("CRM Call Log", result["call_log"])
		self.assertEqual(log.type, "Outgoing")
		self.assertEqual(log.status, "Initiated")
		self.assertEqual(log.receiver, AGENT_EMAIL)
		self.assertEqual(log.caller, AGENT_EMAIL)
		self.assertEqual(log.reference_docname, lead)
		self.assertEqual(getattr(log, "to"), PHONE_CUSTOMER)
		self.assertEqual(getattr(log, "from"), VOICE_NUMBER)

		kwargs = client.calls.create.call_args.kwargs
		self.assertEqual(kwargs["to"], PHONE_AGENT)
		self.assertEqual(kwargs["from_"], VOICE_NUMBER)
		self.assertIn("voice_bridge", kwargs["url"])
		self.assertIn("voice_status", kwargs["status_callback"])

	def test_start_call_without_agent_mobile_raises(self):
		lead = self._create_lead()
		frappe.db.set_value("User", AGENT_EMAIL, "mobile_no", "")
		try:
			with self.assertRaises(outbound.VoiceOutboundError):
				outbound.start_call(lead=lead, agent=AGENT_EMAIL)
		finally:
			frappe.db.set_value("User", AGENT_EMAIL, "mobile_no", PHONE_AGENT)

	def test_start_call_invalid_lead_phone_raises(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "NoPhone",
				"source_channel": "Voice",
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(outbound.VoiceOutboundError):
			outbound.start_call(lead=lead.name, agent=AGENT_EMAIL)
		frappe.delete_doc("CRM Lead", lead.name, ignore_permissions=True, force=True)

	def test_bridge_returns_dial_without_record_by_default(self):
		lead = self._create_lead()
		client, call = self._fake_call("CAbr000000000000000000000000001")
		with patch.object(outbound, "get_client", return_value=client):
			result = outbound.start_call(lead=lead, agent=AGENT_EMAIL)

		twiml = outbound.handle_bridge({"CallSid": result["call_sid"]})
		root = ET.fromstring(twiml)
		dial = root.find("Dial")
		self.assertIsNotNone(dial)
		self.assertIsNone(dial.attrib.get("record"))
		self.assertEqual(dial.find("Number").text, PHONE_CUSTOMER)

	def test_bridge_records_when_prior_consent_and_record_calls_on(self):
		_apply_settings(record_calls=1)
		# Seed prior Call Log with consent for this phone
		frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"id": "CAprev00000000000000000000000001",
				"from": PHONE_CUSTOMER,
				"to": VOICE_NUMBER,
				"type": "Incoming",
				"status": "Completed",
				"telephony_medium": "Twilio",
				"medium": "Voice",
				"consent_recorded": 1,
			}
		).insert(ignore_permissions=True)

		lead = self._create_lead()
		client, call = self._fake_call("CAbr000000000000000000000000002")
		with patch.object(outbound, "get_client", return_value=client):
			result = outbound.start_call(lead=lead, agent=AGENT_EMAIL)

		twiml = outbound.handle_bridge({"CallSid": result["call_sid"]})
		root = ET.fromstring(twiml)
		dial = root.find("Dial")
		self.assertEqual(dial.attrib.get("record"), "record-from-answer")

	def test_bridge_unknown_call_sid_returns_hangup(self):
		twiml = outbound.handle_bridge({"CallSid": "CAnoexist00000000000000000000001"})
		root = ET.fromstring(twiml)
		self.assertIsNotNone(root.find("Hangup"))

	def test_status_callback_updates_status_duration_recording(self):
		lead = self._create_lead()
		client, call = self._fake_call("CAst000000000000000000000000001")
		with patch.object(outbound, "get_client", return_value=client):
			result = outbound.start_call(lead=lead, agent=AGENT_EMAIL)

		outbound.handle_status(
			{
				"CallSid": result["call_sid"],
				"CallStatus": "completed",
				"CallDuration": "42",
				"RecordingUrl": "https://api.twilio.com/rec/abc",
			}
		)
		log = frappe.get_doc("CRM Call Log", result["call_sid"])
		self.assertEqual(log.status, "Completed")
		self.assertEqual(log.duration, 42)
		self.assertEqual(log.recording_url, "https://api.twilio.com/rec/abc")
		self.assertIsNotNone(log.end_time)

	def test_status_callback_ringing_then_completed(self):
		lead = self._create_lead()
		client, call = self._fake_call("CAst000000000000000000000000002")
		with patch.object(outbound, "get_client", return_value=client):
			result = outbound.start_call(lead=lead, agent=AGENT_EMAIL)

		outbound.handle_status({"CallSid": result["call_sid"], "CallStatus": "ringing"})
		log = frappe.get_doc("CRM Call Log", result["call_sid"])
		self.assertEqual(log.status, "Ringing")

		outbound.handle_status(
			{"CallSid": result["call_sid"], "CallStatus": "no-answer"}
		)
		log.reload()
		self.assertEqual(log.status, "No Answer")
		self.assertIsNotNone(log.end_time)

	def test_status_callback_unknown_call_is_noop(self):
		# No exception, no new Call Log
		outbound.handle_status(
			{"CallSid": "CAunknown0000000000000000000000", "CallStatus": "completed"}
		)
		self.assertFalse(
			frappe.db.exists("CRM Call Log", "CAunknown0000000000000000000000")
		)
