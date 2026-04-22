from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from twilio.request_validator import RequestValidator

from imunocare_crm_custom.api import twilio as api_twilio

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_AUTH_TOKEN = "test_auth_token_32bytes_000000000"
TEST_ACCOUNT_SID = "ACtest00000000000000000000000000"
WEBHOOK_URL = "https://imunocare.vps-kinghost.net/api/method/imunocare_crm_custom.api.twilio.webhook"


def _load(name: str) -> dict:
	with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as f:
		return json.load(f)


def _sign(params: dict, url: str = WEBHOOK_URL, token: str = TEST_AUTH_TOKEN) -> str:
	return RequestValidator(token).compute_signature(url, params)


def _build_request(url: str, signature: str):
	req = MagicMock()
	# /api/method/... path
	from urllib.parse import urlparse

	parsed = urlparse(url)
	req.path = parsed.path
	req.host = parsed.netloc
	req.scheme = parsed.scheme
	req.headers = {"X-Twilio-Signature": signature}
	return req


class TestTwilioWebhook(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Twilio Settings")
		cls._orig_sid = settings.account_sid
		cls._orig_token = settings.get_password("auth_token", raise_exception=False) or ""
		settings.account_sid = TEST_ACCOUNT_SID
		settings.auth_token = TEST_AUTH_TOKEN
		settings.save(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		settings = frappe.get_single("Twilio Settings")
		settings.account_sid = cls._orig_sid or ""
		settings.auth_token = cls._orig_token or ""
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.db.delete("Twilio Webhook Event")
		frappe.db.commit()
		frappe.local.response = frappe._dict()
		frappe.local.form_dict = frappe._dict()

	def _call(self, params: dict, signature: str | None = None, url: str = WEBHOOK_URL):
		if signature is None:
			signature = _sign(params, url)
		frappe.local.form_dict = frappe._dict(params)
		frappe.local.request = _build_request(url, signature)
		return api_twilio.webhook()

	def test_channel_detection_whatsapp(self):
		self.assertEqual(api_twilio._detect_channel({"MessageSid": "SMxx"}), "WhatsApp")

	def test_channel_detection_voice(self):
		self.assertEqual(api_twilio._detect_channel({"CallSid": "CAxx"}), "Voice")

	def test_channel_detection_unknown(self):
		self.assertEqual(api_twilio._detect_channel({}), "Unknown")

	def test_whatsapp_valid_signature_creates_event(self):
		params = _load("whatsapp_inbound.json")
		self._call(params)
		self.assertTrue(frappe.db.exists("Twilio Webhook Event", params["MessageSid"]))
		event = frappe.get_doc("Twilio Webhook Event", params["MessageSid"])
		self.assertEqual(event.channel, "WhatsApp")
		self.assertEqual(event.signature_valid, 1)
		self.assertEqual(event.processed, 1)

	def test_voice_valid_signature_creates_event(self):
		params = _load("voice_inbound.json")
		self._call(params)
		self.assertTrue(frappe.db.exists("Twilio Webhook Event", params["CallSid"]))
		event = frappe.get_doc("Twilio Webhook Event", params["CallSid"])
		self.assertEqual(event.channel, "Voice")

	def test_invalid_signature_returns_403(self):
		params = _load("whatsapp_inbound.json")
		self._call(params, signature="invalid_signature")
		self.assertEqual(frappe.local.response.get("http_status_code"), 403)
		self.assertFalse(frappe.db.exists("Twilio Webhook Event", params["MessageSid"]))

	def test_missing_signature_returns_403(self):
		params = _load("whatsapp_inbound.json")
		self._call(params, signature="")
		self.assertEqual(frappe.local.response.get("http_status_code"), 403)
		self.assertFalse(frappe.db.exists("Twilio Webhook Event", params["MessageSid"]))

	def test_replay_does_not_duplicate(self):
		params = _load("whatsapp_inbound.json")
		self._call(params)
		count_after_first = frappe.db.count("Twilio Webhook Event", {"sid": params["MessageSid"]})
		self._call(params)
		count_after_second = frappe.db.count("Twilio Webhook Event", {"sid": params["MessageSid"]})
		self.assertEqual(count_after_first, 1)
		self.assertEqual(count_after_second, 1)

	def test_missing_sid_returns_400(self):
		params = {"AccountSid": TEST_ACCOUNT_SID}
		self._call(params)
		self.assertEqual(frappe.local.response.get("http_status_code"), 400)
