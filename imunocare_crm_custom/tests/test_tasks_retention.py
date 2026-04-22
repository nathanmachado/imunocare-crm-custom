from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from imunocare_crm_custom.tasks import retention

VOICE_NUMBER = "+5511888880000"
PHONE_CUSTOMER = "+5511955550999"
CALL_OLD = "CAret000000000000000000000000001"
CALL_FRESH = "CAret000000000000000000000000002"
RECORDING_OLD_URL = (
	"https://api.twilio.com/2010-04-01/Accounts/ACtest/Recordings/REold00000000000000000000000000001"
)
RECORDING_FRESH_URL = (
	"https://api.twilio.com/2010-04-01/Accounts/ACtest/Recordings/REfresh0000000000000000000000001"
)


def _apply_settings(**kwargs):
	settings = frappe.get_single("Twilio Settings")
	for k, v in kwargs.items():
		setattr(settings, k, v)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()


def _cleanup() -> None:
	for sid in (CALL_OLD, CALL_FRESH):
		if frappe.db.exists("CRM Call Log", sid):
			frappe.delete_doc("CRM Call Log", sid, ignore_permissions=True, force=True)
	frappe.db.commit()


def _mk_call(sid: str, recording_url: str, created_days_ago: int) -> None:
	log = frappe.get_doc(
		{
			"doctype": "CRM Call Log",
			"id": sid,
			"from": VOICE_NUMBER,
			"to": PHONE_CUSTOMER,
			"type": "Outgoing",
			"status": "Completed",
			"telephony_medium": "Twilio",
			"medium": "Voice",
			"recording_url": recording_url,
		}
	).insert(ignore_permissions=True)
	when = add_to_date(now_datetime(), days=-created_days_ago)
	frappe.db.set_value("CRM Call Log", log.name, "creation", when)
	frappe.db.commit()


class TestPurgeOldRecordings(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Twilio Settings")
		cls._orig = {
			"account_sid": settings.account_sid or "",
			"auth_token": settings.get_password("auth_token", raise_exception=False) or "",
			"recording_retention_days": settings.recording_retention_days or 0,
		}
		_apply_settings(
			account_sid="ACtest00000000000000000000000000",
			auth_token="test_auth_token_32bytes_000000000",
			recording_retention_days=30,
		)
		_cleanup()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		_apply_settings(**cls._orig)
		super().tearDownClass()

	def setUp(self):
		_cleanup()

	def test_noop_when_retention_disabled(self):
		_mk_call(CALL_OLD, RECORDING_OLD_URL, created_days_ago=100)
		fake_settings = MagicMock()
		fake_settings.recording_retention_days = 0
		with patch.object(retention, "get_settings", return_value=fake_settings):
			result = retention.purge_old_recordings()
		self.assertEqual(result.get("skipped_reason"), "retention_disabled")

	def test_purges_old_recording_and_clears_url(self):
		_mk_call(CALL_OLD, RECORDING_OLD_URL, created_days_ago=60)

		fake_client = MagicMock()
		with patch.object(retention, "get_client", return_value=fake_client):
			result = retention.purge_old_recordings()

		self.assertEqual(result["purged"], 1)
		fake_client.recordings.assert_called_once_with("REold00000000000000000000000000001")
		fake_client.recordings.return_value.delete.assert_called_once()

		self.assertEqual(
			frappe.db.get_value("CRM Call Log", CALL_OLD, "recording_url") or "", ""
		)

	def test_fresh_recording_is_not_purged(self):
		_mk_call(CALL_FRESH, RECORDING_FRESH_URL, created_days_ago=5)

		fake_client = MagicMock()
		with patch.object(retention, "get_client", return_value=fake_client):
			result = retention.purge_old_recordings()

		self.assertEqual(result["purged"], 0)
		fake_client.recordings.assert_not_called()
		self.assertEqual(
			frappe.db.get_value("CRM Call Log", CALL_FRESH, "recording_url"),
			RECORDING_FRESH_URL,
		)

	def test_extract_sid_from_mp3_url(self):
		self.assertEqual(
			retention._extract_recording_sid(
				"https://api.twilio.com/2010-04-01/Accounts/ACx/Recordings/RE123abc.mp3"
			),
			"RE123abc",
		)

	def test_extract_sid_returns_none_for_bogus_url(self):
		self.assertIsNone(retention._extract_recording_sid("https://example.com/no-sid"))

	def test_twilio_delete_failure_logs_but_continues(self):
		_mk_call(CALL_OLD, RECORDING_OLD_URL, created_days_ago=60)

		fake_client = MagicMock()
		fake_client.recordings.return_value.delete.side_effect = RuntimeError("boom")
		with patch.object(retention, "get_client", return_value=fake_client):
			result = retention.purge_old_recordings()

		self.assertEqual(result["purged"], 0)
		self.assertEqual(result["errors"], 1)
		# URL still present since delete failed
		self.assertEqual(
			frappe.db.get_value("CRM Call Log", CALL_OLD, "recording_url"),
			RECORDING_OLD_URL,
		)
