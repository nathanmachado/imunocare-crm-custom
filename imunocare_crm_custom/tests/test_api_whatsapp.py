from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from imunocare_crm_custom.api import whatsapp as api_whatsapp
from imunocare_crm_custom.channels.whatsapp import sender as wa_sender

PHONE_TEST = "+5511933330001"
WA_SENDER = "+5511888880000"
WA_SENDER_ADDR = f"whatsapp:{WA_SENDER}"

TEST_ACCOUNT_SID = "ACtest00000000000000000000000000"
TEST_AUTH_TOKEN = "test_auth_token_32bytes_000000000"

TEMPLATE_APPROVED = "Imunocare — Boas-vindas Teste"
TEMPLATE_PENDING = "Imunocare — Promo Teste"
CONTENT_SID = "HXtest0000000000000000000000000099"


def _apply_settings(**kwargs):
	settings = frappe.get_single("Twilio Settings")
	for k, v in kwargs.items():
		setattr(settings, k, v)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()


def _cleanup() -> None:
	frappe.db.delete("Communication", filters={"whatsapp_to": ("like", f"%{PHONE_TEST}%")})
	frappe.db.delete("Communication", filters={"whatsapp_from": ("like", f"%{PHONE_TEST}%")})
	for name in frappe.get_all("CRM Lead", filters={"mobile_no": PHONE_TEST}, pluck="name"):
		frappe.delete_doc("CRM Lead", name, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestApiWhatsAppWindowStatus(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Twilio Settings")
		cls._orig_sid = settings.account_sid or ""
		cls._orig_token = settings.get_password("auth_token", raise_exception=False) or ""
		cls._orig_sender = settings.whatsapp_sender or ""
		_apply_settings(
			account_sid=TEST_ACCOUNT_SID,
			auth_token=TEST_AUTH_TOKEN,
			whatsapp_sender=WA_SENDER_ADDR,
		)
		_cleanup()

		for tpl in (TEMPLATE_APPROVED, TEMPLATE_PENDING):
			if frappe.db.exists("Message Template", tpl):
				frappe.delete_doc("Message Template", tpl, ignore_permissions=True, force=True)

		frappe.get_doc(
			{
				"doctype": "Message Template",
				"template_name": TEMPLATE_APPROVED,
				"channel": "WhatsApp",
				"language": "pt_BR",
				"category": "UTILITY",
				"body": "Olá {{1}}, bem-vindo.",
				"twilio_content_sid": CONTENT_SID,
				"approval_status": "Approved",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Message Template",
				"template_name": TEMPLATE_PENDING,
				"channel": "WhatsApp",
				"language": "pt_BR",
				"category": "MARKETING",
				"body": "Promo {{1}}",
				"twilio_content_sid": "HXpending0000000000000000000000001",
				"approval_status": "Pending",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		for tpl in (TEMPLATE_APPROVED, TEMPLATE_PENDING):
			if frappe.db.exists("Message Template", tpl):
				frappe.delete_doc("Message Template", tpl, ignore_permissions=True, force=True)
		_apply_settings(
			account_sid=cls._orig_sid,
			auth_token=cls._orig_token,
			whatsapp_sender=cls._orig_sender,
		)
		super().tearDownClass()

	def setUp(self):
		_cleanup()

	def _create_lead(self) -> str:
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "ApiWA Test",
				"mobile_no": PHONE_TEST,
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
				"twilio_message_sid": f"SMapi{int(hours_ago*1000):020d}",
				"whatsapp_direction": "inbound",
				"whatsapp_status": "received",
				"whatsapp_from": f"whatsapp:{PHONE_TEST}",
				"whatsapp_to": WA_SENDER_ADDR,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Communication", comm.name, "creation", when)
		frappe.db.commit()

	def test_window_open_when_inbound_within_24h(self):
		lead = self._create_lead()
		self._seed_inbound(hours_ago=3)
		result = api_whatsapp.whatsapp_window_status(lead=lead)
		self.assertTrue(result["open"])
		self.assertEqual(result["lead"], lead)
		self.assertEqual(result["phone"], PHONE_TEST)

	def test_window_closed_when_no_inbound(self):
		lead = self._create_lead()
		result = api_whatsapp.whatsapp_window_status(lead=lead)
		self.assertFalse(result["open"])

	def test_templates_only_approved(self):
		lead = self._create_lead()
		result = api_whatsapp.whatsapp_window_status(lead=lead)
		names = [t["name"] for t in result["templates"]]
		self.assertIn(TEMPLATE_APPROVED, names)
		self.assertNotIn(TEMPLATE_PENDING, names)


class TestApiWhatsAppSendRouting(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Twilio Settings")
		cls._orig_sid = settings.account_sid or ""
		cls._orig_token = settings.get_password("auth_token", raise_exception=False) or ""
		cls._orig_sender = settings.whatsapp_sender or ""
		_apply_settings(
			account_sid=TEST_ACCOUNT_SID,
			auth_token=TEST_AUTH_TOKEN,
			whatsapp_sender=WA_SENDER_ADDR,
		)
		_cleanup()
		if not frappe.db.exists("Message Template", TEMPLATE_APPROVED):
			frappe.get_doc(
				{
					"doctype": "Message Template",
					"template_name": TEMPLATE_APPROVED,
					"channel": "WhatsApp",
					"language": "pt_BR",
					"category": "UTILITY",
					"body": "Olá {{1}}, bem-vindo.",
					"twilio_content_sid": CONTENT_SID,
					"approval_status": "Approved",
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		if frappe.db.exists("Message Template", TEMPLATE_APPROVED):
			frappe.delete_doc(
				"Message Template", TEMPLATE_APPROVED, ignore_permissions=True, force=True
			)
		_apply_settings(
			account_sid=cls._orig_sid,
			auth_token=cls._orig_token,
			whatsapp_sender=cls._orig_sender,
		)
		super().tearDownClass()

	def setUp(self):
		_cleanup()

	def _create_lead(self) -> str:
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "ApiWA Route",
				"mobile_no": PHONE_TEST,
				"source_channel": "WhatsApp",
			}
		).insert(ignore_permissions=True)
		return lead.name

	def test_routes_to_free_text_when_body_given(self):
		lead = self._create_lead()
		with patch.object(api_whatsapp.whatsapp_sender, "send_free_text", return_value="COMM-1") as m:
			result = api_whatsapp.send_whatsapp_from_lead(lead=lead, body="Olá")
		m.assert_called_once_with(lead=lead, body="Olá")
		self.assertEqual(result, {"ok": True, "communication": "COMM-1", "mode": "free_text"})

	def test_routes_to_template_when_template_given(self):
		lead = self._create_lead()
		with patch.object(api_whatsapp.whatsapp_sender, "send_template", return_value="COMM-2") as m:
			result = api_whatsapp.send_whatsapp_from_lead(
				lead=lead,
				template=TEMPLATE_APPROVED,
				variables='{"1": "Maria"}',
			)
		m.assert_called_once_with(
			lead=lead, template=TEMPLATE_APPROVED, variables={"1": "Maria"}
		)
		self.assertEqual(result["mode"], "template")

	def test_template_takes_precedence_over_body(self):
		lead = self._create_lead()
		with patch.object(api_whatsapp.whatsapp_sender, "send_template", return_value="COMM-3") as m:
			api_whatsapp.send_whatsapp_from_lead(
				lead=lead, body="ignored", template=TEMPLATE_APPROVED
			)
		m.assert_called_once()

	def test_empty_body_without_template_raises(self):
		lead = self._create_lead()
		with self.assertRaises(frappe.ValidationError):
			api_whatsapp.send_whatsapp_from_lead(lead=lead, body="   ")

	def test_invalid_variables_json_raises(self):
		lead = self._create_lead()
		with self.assertRaises(frappe.ValidationError):
			api_whatsapp.send_whatsapp_from_lead(
				lead=lead, template=TEMPLATE_APPROVED, variables="not-json"
			)

	def test_variables_dict_passthrough(self):
		lead = self._create_lead()
		with patch.object(api_whatsapp.whatsapp_sender, "send_template", return_value="COMM-4") as m:
			api_whatsapp.send_whatsapp_from_lead(
				lead=lead, template=TEMPLATE_APPROVED, variables={"1": "Ana"}
			)
		m.assert_called_once_with(
			lead=lead, template=TEMPLATE_APPROVED, variables={"1": "Ana"}
		)
