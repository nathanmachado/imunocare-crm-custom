from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.channels.base import (
	ensure_contact,
	get_or_create_lead,
	resolve_contact,
	resolve_patient,
)

PHONE_PATIENT = "+5511977777777"
PHONE_CONTACT_ONLY = "+5511966666666"
PHONE_UNKNOWN = "+5511955555555"


def _cleanup():
	frappe.db.delete("CRM Lead", filters={"mobile_no": ("in", [PHONE_PATIENT, PHONE_CONTACT_ONLY, PHONE_UNKNOWN])})
	for phone in (PHONE_PATIENT, PHONE_CONTACT_ONLY, PHONE_UNKNOWN):
		for cp in frappe.get_all("Contact Phone", filters={"phone": phone}, pluck="parent"):
			try:
				frappe.delete_doc("Contact", cp, ignore_permissions=True, force=True)
			except Exception:
				pass
	for name in frappe.get_all("Patient", filters={"mobile": PHONE_PATIENT}, pluck="name"):
		frappe.delete_doc("Patient", name, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestChannelsBase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_cleanup()
		# Paciente com Contact vinculado (simulando dado real do Healthcare)
		cls.patient_name = frappe.get_doc(
			{
				"doctype": "Patient",
				"first_name": "Paciente",
				"last_name": "Existente",
				"mobile": PHONE_PATIENT,
				"sex": "Male",
			}
		).insert(ignore_permissions=True).name

		# Contact sem Patient linkado (apenas contato comercial)
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Contato",
				"last_name": "SemPaciente",
				"phone_nos": [{"phone": PHONE_CONTACT_ONLY, "is_primary_mobile_no": 1}],
			}
		).insert(ignore_permissions=True)
		cls.contact_only_name = contact.name
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		super().tearDownClass()

	def test_resolve_patient_by_mobile(self):
		self.assertEqual(resolve_patient(PHONE_PATIENT), self.patient_name)

	def test_resolve_patient_accepts_masked(self):
		self.assertEqual(resolve_patient("(11) 97777-7777"), self.patient_name)

	def test_resolve_patient_none_for_unknown(self):
		self.assertIsNone(resolve_patient(PHONE_UNKNOWN))

	def test_resolve_contact_by_phone_nos(self):
		self.assertEqual(resolve_contact(PHONE_CONTACT_ONLY), self.contact_only_name)

	def test_ensure_contact_creates_when_missing(self):
		name = ensure_contact(PHONE_UNKNOWN, display_name="Novo Lead")
		self.assertTrue(frappe.db.exists("Contact", name))
		self.addCleanup(lambda: frappe.delete_doc("Contact", name, ignore_permissions=True, force=True))

	def test_get_or_create_lead_patient_linked(self):
		lead_name = get_or_create_lead(PHONE_PATIENT, "WhatsApp", display_name="Paciente Existente")
		lead = frappe.get_doc("CRM Lead", lead_name)
		self.assertEqual(lead.patient, self.patient_name)
		self.assertEqual(lead.source_channel, "WhatsApp")
		self.assertEqual(lead.mobile_no, PHONE_PATIENT)
		self.assertIsNotNone(lead.first_contact_at)

	def test_get_or_create_lead_contact_without_patient(self):
		lead_name = get_or_create_lead(PHONE_CONTACT_ONLY, "Voice", display_name="Sem Paciente")
		lead = frappe.get_doc("CRM Lead", lead_name)
		self.assertFalse(lead.patient)
		self.assertEqual(lead.source_channel, "Voice")

	def test_get_or_create_lead_new_contact(self):
		before_contacts = frappe.db.count("Contact")
		lead_name = get_or_create_lead(PHONE_UNKNOWN, "WhatsApp", display_name="Contato Novo")
		lead = frappe.get_doc("CRM Lead", lead_name)
		self.assertFalse(lead.patient)
		self.assertEqual(lead.mobile_no, PHONE_UNKNOWN)
		self.assertGreater(frappe.db.count("Contact"), before_contacts)

	def test_open_lead_is_reused_and_last_contact_updated(self):
		first = get_or_create_lead(PHONE_CONTACT_ONLY, "Voice", display_name="Sem Paciente")
		first_doc = frappe.get_doc("CRM Lead", first)
		first_contact_time = first_doc.first_contact_at

		second = get_or_create_lead(PHONE_CONTACT_ONLY, "WhatsApp", display_name="Sem Paciente")
		self.assertEqual(second, first)
		second_doc = frappe.get_doc("CRM Lead", second)
		self.assertEqual(second_doc.first_contact_at, first_contact_time)
		self.assertGreaterEqual(second_doc.last_contact_at, first_contact_time)

	def test_invalid_phone_raises(self):
		with self.assertRaises(frappe.ValidationError):
			get_or_create_lead("abc", "WhatsApp")
