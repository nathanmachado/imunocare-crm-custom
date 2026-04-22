from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.channels.voice import handlers as voice_handlers

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

PHONE_CALLER = "+5511966666666"
PHONE_AGENT = "+5511955555555"
AGENT_EMAIL = "voice-agent@example.com"

TEST_ACCOUNT_SID = "ACtest00000000000000000000000000"
TEST_AUTH_TOKEN = "test_auth_token_32bytes_000000000"
TEST_VOICE_NUMBER = "+5511888888888"
TEST_WEBHOOK_BASE = "https://imunocare.vps-kinghost.net"


def _load(name: str) -> dict:
	with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as f:
		return json.load(f)


def _cleanup_for_phone(phone: str) -> None:
	for name in frappe.get_all("CRM Call Log", filters={"from": phone}, pluck="name"):
		frappe.delete_doc("CRM Call Log", name, ignore_permissions=True, force=True)
	for name in frappe.get_all("CRM Lead", filters={"mobile_no": phone}, pluck="name"):
		for todo in frappe.get_all(
			"ToDo", filters={"reference_type": "CRM Lead", "reference_name": name}, pluck="name"
		):
			frappe.delete_doc("ToDo", todo, ignore_permissions=True, force=True)
		frappe.delete_doc("CRM Lead", name, ignore_permissions=True, force=True)
	for cp in frappe.get_all("Contact Phone", filters={"phone": phone}, pluck="parent"):
		try:
			frappe.delete_doc("Contact", cp, ignore_permissions=True, force=True)
		except Exception:
			pass
	for name in frappe.get_all("Patient", filters={"mobile": phone}, pluck="name"):
		frappe.delete_doc("Patient", name, ignore_permissions=True, force=True)
	frappe.db.commit()


def _get_settings_snapshot():
	settings = frappe.get_single("Twilio Settings")
	return {
		"account_sid": settings.account_sid or "",
		"auth_token": settings.get_password("auth_token", raise_exception=False) or "",
		"voice_number": settings.voice_number or "",
		"webhook_base_url": settings.webhook_base_url or "",
		"record_calls": settings.record_calls or 0,
	}


def _apply_settings(**kwargs):
	settings = frappe.get_single("Twilio Settings")
	for k, v in kwargs.items():
		setattr(settings, k, v)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()


class TestVoiceInboundHandler(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._orig = _get_settings_snapshot()
		_apply_settings(
			account_sid=TEST_ACCOUNT_SID,
			auth_token=TEST_AUTH_TOKEN,
			voice_number=TEST_VOICE_NUMBER,
			webhook_base_url=TEST_WEBHOOK_BASE,
			record_calls=0,
		)
		_cleanup_for_phone(PHONE_CALLER)

		if not frappe.db.exists("User", AGENT_EMAIL):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": AGENT_EMAIL,
					"first_name": "Voice",
					"last_name": "Agent",
					"mobile_no": PHONE_AGENT,
					"send_welcome_email": 0,
					"enabled": 1,
				}
			)
			user.insert(ignore_permissions=True)
		else:
			frappe.db.set_value("User", AGENT_EMAIL, "mobile_no", PHONE_AGENT)
		cls.agent = AGENT_EMAIL
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup_for_phone(PHONE_CALLER)
		if frappe.db.exists("User", AGENT_EMAIL):
			frappe.delete_doc("User", AGENT_EMAIL, ignore_permissions=True, force=True)
		_apply_settings(**cls._orig)
		super().tearDownClass()

	def setUp(self):
		_cleanup_for_phone(PHONE_CALLER)
		_apply_settings(record_calls=0)

	def _payload(self, call_sid: str | None = None) -> dict:
		p = dict(_load("voice_inbound.json"))
		p["From"] = PHONE_CALLER
		p["To"] = TEST_VOICE_NUMBER
		if call_sid:
			p["CallSid"] = call_sid
		return p

	def _create_open_todo(self, lead_name: str, user: str) -> str:
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"reference_type": "CRM Lead",
				"reference_name": lead_name,
				"allocated_to": user,
				"status": "Open",
				"description": "Test assignment",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		return todo.name

	def _seed_lead_with_assignment(self, phone: str, user: str) -> str:
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Caller",
				"mobile_no": phone,
				"phone": phone,
				"source_channel": "Voice",
			}
		).insert(ignore_permissions=True)
		self._create_open_todo(lead.name, user)
		return lead.name

	def test_missed_call_no_assignee_marks_lead_and_creates_todo(self):
		payload = self._payload("CAmiss0000000000000000000000000001")
		twiml = voice_handlers.handle_inbound(payload)

		self.assertIn("<Say", twiml)
		self.assertIn("Obrigado pelo contato", twiml)

		call_log = frappe.get_doc("CRM Call Log", payload["CallSid"])
		self.assertEqual(call_log.status, "No Answer")
		self.assertEqual(call_log.type, "Incoming")
		self.assertEqual(getattr(call_log, "from"), PHONE_CALLER)

		lead = frappe.get_doc("CRM Lead", call_log.reference_docname)
		self.assertEqual(lead.status, "Missed Call")

		todos = frappe.get_all(
			"ToDo",
			filters={"reference_type": "CRM Lead", "reference_name": lead.name, "status": "Open"},
			fields=["priority", "description"],
		)
		self.assertTrue(any(payload["CallSid"] in (t.description or "") for t in todos))
		self.assertTrue(any(t.priority == "High" for t in todos))

	def test_attended_call_without_recording_returns_dial(self):
		self._seed_lead_with_assignment(PHONE_CALLER, self.agent)
		payload = self._payload("CAatt00000000000000000000000000001")

		twiml = voice_handlers.handle_inbound(payload)

		root = ET.fromstring(twiml)
		dial = root.find("Dial")
		self.assertIsNotNone(dial)
		self.assertIsNone(dial.attrib.get("record"))
		self.assertEqual(dial.attrib.get("callerId"), TEST_VOICE_NUMBER)
		number = dial.find("Number")
		self.assertIsNotNone(number)
		self.assertEqual(number.text, PHONE_AGENT)

		call_log = frappe.get_doc("CRM Call Log", payload["CallSid"])
		self.assertEqual(call_log.status, "Ringing")
		self.assertEqual(call_log.receiver, self.agent)

	def test_attended_call_with_recording_returns_gather(self):
		_apply_settings(record_calls=1)
		self._seed_lead_with_assignment(PHONE_CALLER, self.agent)
		payload = self._payload("CAivr00000000000000000000000000001")

		twiml = voice_handlers.handle_inbound(payload)

		root = ET.fromstring(twiml)
		gather = root.find("Gather")
		self.assertIsNotNone(gather)
		self.assertEqual(gather.attrib.get("numDigits"), "1")
		self.assertIn("voice_consent", gather.attrib.get("action", ""))
		say = gather.find("Say")
		self.assertIsNotNone(say)
		self.assertIn("gravada", say.text or "")

	def test_invalid_phone_returns_voicemail(self):
		payload = self._payload("CAbad00000000000000000000000000001")
		payload["From"] = "abc"

		twiml = voice_handlers.handle_inbound(payload)

		self.assertIn("<Say", twiml)
		self.assertFalse(frappe.db.exists("CRM Call Log", payload["CallSid"]))

	def test_missing_call_sid_returns_voicemail(self):
		payload = self._payload()
		payload["CallSid"] = ""

		twiml = voice_handlers.handle_inbound(payload)
		self.assertIn("<Hangup", twiml) or self.assertIn("<Say", twiml)

	def test_replay_same_call_sid_is_idempotent(self):
		payload = self._payload("CArpl00000000000000000000000000001")
		first = voice_handlers.handle_inbound(payload)
		second = voice_handlers.handle_inbound(payload)
		self.assertIn("<Say", second)
		count = frappe.db.count("CRM Call Log", {"id": payload["CallSid"]})
		self.assertEqual(count, 1)
		self.assertIsNotNone(first)

	def test_consent_response_granted_returns_dial_with_record(self):
		_apply_settings(record_calls=1)
		self._seed_lead_with_assignment(PHONE_CALLER, self.agent)
		call_sid = "CAcon00000000000000000000000000001"
		voice_handlers.handle_inbound(self._payload(call_sid))

		twiml = voice_handlers.handle_consent_response({"CallSid": call_sid, "Digits": "1"})
		root = ET.fromstring(twiml)
		dial = root.find("Dial")
		self.assertIsNotNone(dial)
		self.assertEqual(dial.attrib.get("record"), "record-from-answer")

		call_log = frappe.get_doc("CRM Call Log", call_sid)
		self.assertEqual(call_log.consent_recorded, 1)

	def test_consent_response_denied_returns_dial_without_record(self):
		_apply_settings(record_calls=1)
		self._seed_lead_with_assignment(PHONE_CALLER, self.agent)
		call_sid = "CAcon00000000000000000000000000002"
		voice_handlers.handle_inbound(self._payload(call_sid))

		twiml = voice_handlers.handle_consent_response({"CallSid": call_sid, "Digits": "0"})
		root = ET.fromstring(twiml)
		dial = root.find("Dial")
		self.assertIsNotNone(dial)
		self.assertIsNone(dial.attrib.get("record"))

		call_log = frappe.get_doc("CRM Call Log", call_sid)
		self.assertEqual(call_log.consent_recorded, 0)

	def test_consent_response_unknown_call_returns_voicemail(self):
		twiml = voice_handlers.handle_consent_response(
			{"CallSid": "CAnotexist00000000000000000000000", "Digits": "1"}
		)
		self.assertIn("<Say", twiml)

	def test_twiml_outputs_are_valid_xml(self):
		_apply_settings(record_calls=1)
		self._seed_lead_with_assignment(PHONE_CALLER, self.agent)
		payload = self._payload("CAxml00000000000000000000000000001")

		inbound_twiml = voice_handlers.handle_inbound(payload)
		ET.fromstring(inbound_twiml)  # não deve lançar

		consent_twiml = voice_handlers.handle_consent_response(
			{"CallSid": payload["CallSid"], "Digits": "1"}
		)
		ET.fromstring(consent_twiml)
