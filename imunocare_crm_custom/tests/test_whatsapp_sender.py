from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from imunocare_crm_custom.channels.whatsapp import sender as wa_sender

PHONE_TEST = "+5511955550001"
WA_SENDER = "+5511888880000"
WA_SENDER_ADDR = f"whatsapp:{WA_SENDER}"

TEST_ACCOUNT_SID = "ACtest00000000000000000000000000"
TEST_AUTH_TOKEN = "test_auth_token_32bytes_000000000"

TEMPLATE_NAME = "Imunocare — Lembrete Consulta"
CONTENT_SID = "HXtest0000000000000000000000000001"


def _cleanup() -> None:
	frappe.db.delete("Communication", filters={"whatsapp_to": ("like", f"%{PHONE_TEST}%")})
	frappe.db.delete("Communication", filters={"whatsapp_from": ("like", f"%{PHONE_TEST}%")})
	for name in frappe.get_all("CRM Lead", filters={"mobile_no": PHONE_TEST}, pluck="name"):
		frappe.delete_doc("CRM Lead", name, ignore_permissions=True, force=True)
	for cp in frappe.get_all("Contact Phone", filters={"phone": PHONE_TEST}, pluck="parent"):
		try:
			frappe.delete_doc("Contact", cp, ignore_permissions=True, force=True)
		except Exception:
			pass
	frappe.db.commit()


def _apply_settings(**kwargs):
	settings = frappe.get_single("Twilio Settings")
	for k, v in kwargs.items():
		setattr(settings, k, v)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()


class TestWhatsAppSender(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Twilio Settings")
		cls._orig_sid = settings.account_sid or ""
		cls._orig_token = settings.get_password("auth_token", raise_exception=False) or ""
		cls._orig_sender = settings.whatsapp_sender or ""
		cls._orig_base = settings.webhook_base_url or ""
		_apply_settings(
			account_sid=TEST_ACCOUNT_SID,
			auth_token=TEST_AUTH_TOKEN,
			whatsapp_sender=WA_SENDER_ADDR,
			webhook_base_url="https://imunocare.vps-kinghost.net",
		)
		_cleanup()

		if frappe.db.exists("Message Template", TEMPLATE_NAME):
			frappe.delete_doc("Message Template", TEMPLATE_NAME, ignore_permissions=True, force=True)
		frappe.get_doc(
			{
				"doctype": "Message Template",
				"template_name": TEMPLATE_NAME,
				"channel": "WhatsApp",
				"language": "pt_BR",
				"category": "UTILITY",
				"body": "Olá {{1}}, sua consulta é {{2}}.",
				"twilio_content_sid": CONTENT_SID,
				"approval_status": "Approved",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		if frappe.db.exists("Message Template", TEMPLATE_NAME):
			frappe.delete_doc("Message Template", TEMPLATE_NAME, ignore_permissions=True, force=True)
		_apply_settings(
			account_sid=cls._orig_sid,
			auth_token=cls._orig_token,
			whatsapp_sender=cls._orig_sender,
			webhook_base_url=cls._orig_base,
		)
		super().tearDownClass()

	def setUp(self):
		_cleanup()

	def _create_lead(self) -> str:
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Sender Test",
				"mobile_no": PHONE_TEST,
				"phone": PHONE_TEST,
				"source_channel": "WhatsApp",
			}
		).insert(ignore_permissions=True)
		return lead.name

	def _seed_inbound(self, hours_ago: float) -> None:
		when = add_to_date(now_datetime(), hours=-hours_ago)
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "WhatsApp",
				"sent_or_received": "Received",
				"content": "oi",
				"status": "Open",
				"twilio_message_sid": f"SMfake{int(hours_ago*10):020d}",
				"whatsapp_direction": "inbound",
				"whatsapp_status": "received",
				"whatsapp_from": f"whatsapp:{PHONE_TEST}",
				"whatsapp_to": WA_SENDER_ADDR,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Communication", comm.name, "creation", when)
		frappe.db.commit()

	def test_free_text_blocked_outside_24h_window(self):
		lead = self._create_lead()
		self._seed_inbound(hours_ago=30)

		with self.assertRaises(wa_sender.WhatsAppWindowClosed):
			wa_sender.send_free_text(lead, "oi, tudo bem?")

	def test_free_text_allowed_inside_24h_window(self):
		lead = self._create_lead()
		self._seed_inbound(hours_ago=2)

		fake_msg = MagicMock()
		fake_msg.sid = "SMout000000000000000000000000001"
		fake_client = MagicMock()
		fake_client.messages.create.return_value = fake_msg

		with patch.object(wa_sender, "get_client", return_value=fake_client):
			comm_name = wa_sender.send_free_text(lead, "Olá, retornando seu contato.")

		comm = frappe.get_doc("Communication", comm_name)
		self.assertEqual(comm.whatsapp_direction, "outbound")
		self.assertEqual(comm.whatsapp_status, "queued")
		self.assertEqual(comm.sent_or_received, "Sent")
		self.assertEqual(comm.twilio_message_sid, fake_msg.sid)
		self.assertEqual(comm.reference_name, lead)
		fake_client.messages.create.assert_called_once()
		call_kwargs = fake_client.messages.create.call_args.kwargs
		self.assertEqual(call_kwargs["from_"], WA_SENDER_ADDR)
		self.assertEqual(call_kwargs["to"], f"whatsapp:{PHONE_TEST}")
		self.assertEqual(call_kwargs["body"], "Olá, retornando seu contato.")
		self.assertIn("message_status", call_kwargs["status_callback"])

	def test_template_always_allowed_even_outside_window(self):
		lead = self._create_lead()
		self._seed_inbound(hours_ago=48)

		fake_msg = MagicMock()
		fake_msg.sid = "SMtpl000000000000000000000000001"
		fake_client = MagicMock()
		fake_client.messages.create.return_value = fake_msg

		with patch.object(wa_sender, "get_client", return_value=fake_client):
			comm_name = wa_sender.send_template(
				lead, TEMPLATE_NAME, variables={"1": "Paciente", "2": "amanhã 14h"}
			)

		comm = frappe.get_doc("Communication", comm_name)
		self.assertEqual(comm.whatsapp_direction, "outbound")
		self.assertEqual(comm.twilio_message_sid, fake_msg.sid)
		self.assertIn("Paciente", comm.content)
		self.assertIn("amanhã 14h", comm.content)

		call_kwargs = fake_client.messages.create.call_args.kwargs
		self.assertEqual(call_kwargs["content_sid"], CONTENT_SID)
		self.assertIn("Paciente", call_kwargs["content_variables"])

	def test_template_not_approved_blocks_send(self):
		lead = self._create_lead()
		frappe.db.set_value("Message Template", TEMPLATE_NAME, "approval_status", "Pending")
		try:
			with self.assertRaises(wa_sender.WhatsAppTemplateNotApproved):
				wa_sender.send_template(lead, TEMPLATE_NAME, variables={"1": "x", "2": "y"})
		finally:
			frappe.db.set_value("Message Template", TEMPLATE_NAME, "approval_status", "Approved")

	def test_update_status_from_callback_updates_communication(self):
		lead = self._create_lead()
		sid = "SMcb0000000000000000000000000001"
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "WhatsApp",
				"sent_or_received": "Sent",
				"content": "x",
				"reference_doctype": "CRM Lead",
				"reference_name": lead,
				"status": "Linked",
				"twilio_message_sid": sid,
				"whatsapp_direction": "outbound",
				"whatsapp_status": "queued",
			}
		).insert(ignore_permissions=True)

		result = wa_sender.update_status_from_callback(sid, "delivered")
		self.assertIsNotNone(result)
		self.assertEqual(
			frappe.db.get_value("Communication", result, "whatsapp_status"), "delivered"
		)

	def test_update_status_unknown_sid_returns_none(self):
		self.assertIsNone(wa_sender.update_status_from_callback("SMnotexist", "delivered"))

	def test_is_within_24h_window_true_false(self):
		self.assertFalse(wa_sender.is_within_24h_window(PHONE_TEST))
		self._seed_inbound(hours_ago=1)
		self.assertTrue(wa_sender.is_within_24h_window(PHONE_TEST))
