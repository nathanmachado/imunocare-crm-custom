from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.api import twilio as api_twilio

VOICE_NUMBER = "+5511888880000"
PHONE_CUSTOMER = "+5511955550999"
CALL_SID = "CArec000000000000000000000000001"
CALL_SID_NO_REC = "CArec000000000000000000000000002"

TEST_ACCOUNT_SID = "ACtest00000000000000000000000000"
TEST_AUTH_TOKEN = "test_auth_token_32bytes_000000000"
RECORDING_URL = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Recordings/RE00000000000000000000000000000001"


def _apply_settings(**kwargs):
	settings = frappe.get_single("Twilio Settings")
	for k, v in kwargs.items():
		setattr(settings, k, v)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()


def _cleanup() -> None:
	for sid in (CALL_SID, CALL_SID_NO_REC):
		if frappe.db.exists("CRM Call Log", sid):
			frappe.delete_doc("CRM Call Log", sid, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestRecordingProxy(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Twilio Settings")
		cls._orig = {
			"account_sid": settings.account_sid or "",
			"auth_token": settings.get_password("auth_token", raise_exception=False) or "",
		}
		_apply_settings(account_sid=TEST_ACCOUNT_SID, auth_token=TEST_AUTH_TOKEN)
		_cleanup()
		frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"id": CALL_SID,
				"from": VOICE_NUMBER,
				"to": PHONE_CUSTOMER,
				"type": "Outgoing",
				"status": "Completed",
				"telephony_medium": "Twilio",
				"medium": "Voice",
				"recording_url": RECORDING_URL,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"id": CALL_SID_NO_REC,
				"from": VOICE_NUMBER,
				"to": PHONE_CUSTOMER,
				"type": "Outgoing",
				"status": "Completed",
				"telephony_medium": "Twilio",
				"medium": "Voice",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		_apply_settings(**cls._orig)
		super().tearDownClass()

	def setUp(self):
		frappe.local.response = frappe._dict()

	def test_missing_call_sid_raises(self):
		with self.assertRaises(frappe.ValidationError):
			api_twilio.recording_proxy(call_sid="")

	def test_unknown_call_sid_returns_404(self):
		result = api_twilio.recording_proxy(call_sid="CAnoexist00000000000000000000099")
		self.assertEqual(frappe.local.response.get("http_status_code"), 404)
		self.assertEqual(result.get("error"), "call_log_not_found")

	def test_call_without_recording_returns_404(self):
		result = api_twilio.recording_proxy(call_sid=CALL_SID_NO_REC)
		self.assertEqual(frappe.local.response.get("http_status_code"), 404)
		self.assertEqual(result.get("error"), "recording_not_available")

	def test_proxy_fetches_with_basic_auth_and_returns_binary(self):
		fake_response = MagicMock()
		fake_response.status_code = 200
		fake_response.content = b"\x00\x01\x02audio-bytes"

		with patch("requests.get", return_value=fake_response) as fake_get:
			api_twilio.recording_proxy(call_sid=CALL_SID)

		fake_get.assert_called_once()
		args, kwargs = fake_get.call_args
		self.assertEqual(args[0], RECORDING_URL + ".mp3")
		self.assertEqual(kwargs["auth"], (TEST_ACCOUNT_SID, TEST_AUTH_TOKEN))

		self.assertEqual(frappe.local.response.type, "binary")
		self.assertEqual(frappe.local.response.filecontent, b"\x00\x01\x02audio-bytes")
		self.assertEqual(frappe.local.response.filename, f"call_{CALL_SID}.mp3")

	def test_proxy_upstream_failure_returns_502(self):
		fake_response = MagicMock()
		fake_response.status_code = 404
		fake_response.content = b""

		with patch("requests.get", return_value=fake_response):
			result = api_twilio.recording_proxy(call_sid=CALL_SID)

		self.assertEqual(frappe.local.response.get("http_status_code"), 502)
		self.assertTrue(result["error"].startswith("upstream_status_"))

	def test_proxy_twilio_not_configured_returns_503(self):
		_apply_settings(account_sid="", auth_token="")
		try:
			result = api_twilio.recording_proxy(call_sid=CALL_SID)
			self.assertEqual(frappe.local.response.get("http_status_code"), 503)
			self.assertEqual(result["error"], "twilio_not_configured")
		finally:
			_apply_settings(account_sid=TEST_ACCOUNT_SID, auth_token=TEST_AUTH_TOKEN)
