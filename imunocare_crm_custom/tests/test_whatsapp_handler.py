from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.channels.whatsapp import handlers as wa_handlers

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

PHONE_TEST = "+5511977777777"
TEST_ACCOUNT_SID = "ACtest00000000000000000000000000"
TEST_AUTH_TOKEN = "test_auth_token_32bytes_000000000"


def _load(name: str) -> dict:
	with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as f:
		return json.load(f)


def _cleanup_for_phone(phone: str) -> None:
	sids = frappe.get_all("Communication", filters={"sender": ("like", f"%{phone[1:]}%")}, pluck="name")
	for s in sids:
		frappe.delete_doc("Communication", s, ignore_permissions=True, force=True)
	frappe.db.delete("CRM Lead", filters={"mobile_no": phone})
	for cp in frappe.get_all("Contact Phone", filters={"phone": phone}, pluck="parent"):
		try:
			frappe.delete_doc("Contact", cp, ignore_permissions=True, force=True)
		except Exception:
			pass
	for name in frappe.get_all("Patient", filters={"mobile": phone}, pluck="name"):
		frappe.delete_doc("Patient", name, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestWhatsAppInboundHandler(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Twilio Settings")
		cls._orig_sid = settings.account_sid
		cls._orig_token = settings.get_password("auth_token", raise_exception=False) or ""
		settings.account_sid = TEST_ACCOUNT_SID
		settings.auth_token = TEST_AUTH_TOKEN
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		_cleanup_for_phone(PHONE_TEST)
		cls.patient_name = frappe.get_doc(
			{
				"doctype": "Patient",
				"first_name": "Paciente",
				"last_name": "Existente",
				"mobile": PHONE_TEST,
				"sex": "Male",
			}
		).insert(ignore_permissions=True).name
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup_for_phone(PHONE_TEST)
		settings = frappe.get_single("Twilio Settings")
		settings.account_sid = cls._orig_sid or ""
		settings.auth_token = cls._orig_token or ""
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.db.delete("Communication", filters={"twilio_message_sid": ("is", "set")})
		frappe.db.delete("CRM Lead", filters={"mobile_no": PHONE_TEST})
		frappe.db.commit()

	def test_text_message_creates_communication_linked_to_patient_lead(self):
		payload = _load("whatsapp_inbound.json")
		payload["From"] = f"whatsapp:{PHONE_TEST}"
		payload["ProfileName"] = "Paciente Existente"

		comm_name = wa_handlers.handle_inbound(payload)
		comm = frappe.get_doc("Communication", comm_name)
		self.assertEqual(comm.communication_medium, "WhatsApp")
		self.assertEqual(comm.sent_or_received, "Received")
		self.assertEqual(comm.whatsapp_direction, "inbound")
		self.assertEqual(comm.whatsapp_status, "received")
		self.assertEqual(comm.twilio_message_sid, payload["MessageSid"])
		self.assertEqual(comm.reference_doctype, "CRM Lead")
		self.assertTrue(comm.content)

		lead = frappe.get_doc("CRM Lead", comm.reference_name)
		self.assertEqual(lead.patient, self.patient_name)
		self.assertEqual(lead.source_channel, "WhatsApp")

	def test_replay_same_sid_returns_existing_communication(self):
		payload = _load("whatsapp_inbound.json")
		payload["From"] = f"whatsapp:{PHONE_TEST}"

		first = wa_handlers.handle_inbound(payload)
		second = wa_handlers.handle_inbound(payload)
		self.assertEqual(first, second)
		count = frappe.db.count("Communication", {"twilio_message_sid": payload["MessageSid"]})
		self.assertEqual(count, 1)

	def test_invalid_phone_logs_and_returns_none(self):
		payload = dict(_load("whatsapp_inbound.json"))
		payload["From"] = "whatsapp:abc"
		payload["MessageSid"] = "SMinvalidphone11111111111111111111"
		result = wa_handlers.handle_inbound(payload)
		self.assertIsNone(result)

	def test_missing_sid_returns_none(self):
		payload = dict(_load("whatsapp_inbound.json"))
		payload["MessageSid"] = ""
		result = wa_handlers.handle_inbound(payload)
		self.assertIsNone(result)

	def test_image_payload_attaches_file(self):
		import io

		from PIL import Image

		payload = _load("whatsapp_with_image.json")
		payload["From"] = f"whatsapp:{PHONE_TEST}"

		img_buf = io.BytesIO()
		Image.new("RGB", (1, 1), color="red").save(img_buf, format="JPEG")

		fake_response = MagicMock()
		fake_response.content = img_buf.getvalue()
		fake_response.raise_for_status = MagicMock()

		with patch.object(wa_handlers.requests, "get", return_value=fake_response) as mock_get:
			comm_name = wa_handlers.handle_inbound(payload)

		self.assertIsNotNone(comm_name)
		mock_get.assert_called_once()
		call_args = mock_get.call_args
		self.assertEqual(call_args.kwargs["auth"], (TEST_ACCOUNT_SID, TEST_AUTH_TOKEN))

		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Communication", "attached_to_name": comm_name},
			fields=["file_name", "is_private"],
		)
		self.assertEqual(len(files), 1)
		self.assertTrue(files[0].file_name.endswith(".jpg") or files[0].file_name.endswith(".jpe") or files[0].file_name.endswith(".jpeg"))
		self.assertEqual(files[0].is_private, 1)

	def test_media_download_failure_still_creates_communication(self):
		payload = _load("whatsapp_with_image.json")
		payload["From"] = f"whatsapp:{PHONE_TEST}"
		payload["MessageSid"] = "SMcccfailurecase1111111111111111111"

		with patch.object(wa_handlers.requests, "get", side_effect=Exception("network error")):
			comm_name = wa_handlers.handle_inbound(payload)

		self.assertIsNotNone(comm_name)
		self.assertTrue(frappe.db.exists("Communication", comm_name))
		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Communication", "attached_to_name": comm_name},
		)
		self.assertEqual(len(files), 0)
