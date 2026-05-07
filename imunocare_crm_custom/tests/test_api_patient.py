from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.api import patient as patient_api

PHONE_EXISTING = "+5511922222222"
PHONE_NEW = "+5511911111111"
PHONE_DUPLICATE = "+5511900000000"


def _cleanup() -> None:
	for lead in frappe.get_all(
		"CRM Lead",
		filters={"mobile_no": ("in", [PHONE_EXISTING, PHONE_NEW, PHONE_DUPLICATE])},
		pluck="name",
	):
		frappe.db.delete(
			"Communication", {"reference_doctype": "CRM Lead", "reference_name": lead}
		)
		frappe.db.delete(
			"CRM Call Log", {"reference_doctype": "CRM Lead", "reference_docname": lead}
		)
		frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
	for phone in (PHONE_EXISTING, PHONE_NEW, PHONE_DUPLICATE):
		for cp in frappe.get_all(
			"Contact Phone", filters={"phone": phone}, pluck="parent"
		):
			try:
				frappe.delete_doc("Contact", cp, ignore_permissions=True, force=True)
			except Exception:
				pass
	for phone in (PHONE_EXISTING, PHONE_NEW, PHONE_DUPLICATE):
		for name in frappe.get_all("Patient", filters={"mobile": phone}, pluck="name"):
			frappe.delete_doc("Patient", name, ignore_permissions=True, force=True)
	# Limpa Users criados em runs anteriores (Healthcare invite_user)
	for email in ("pedro@example.com", "nova@example.com", "maria@override.com"):
		if frappe.db.exists("User", email):
			try:
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
			except Exception:
				pass
	frappe.db.commit()


class TestApiPatient(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_cleanup()

		cls.existing_patient = (
			frappe.get_doc(
				{
					"doctype": "Patient",
					"first_name": "Pedro",
					"last_name": "Almeida",
					"mobile": PHONE_EXISTING,
					"sex": "Male",
					"email": "pedro@example.com",
					"invite_user": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		cls.duplicate_patient = (
			frappe.get_doc(
				{
					"doctype": "Patient",
					"first_name": "Existente",
					"last_name": "Duplicado",
					"mobile": PHONE_DUPLICATE,
					"sex": "Female",
					"invite_user": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		self._reset_phone_new_state()

	def _reset_phone_new_state(self) -> None:
		"""Limpa Leads/Patients/Contacts associados ao PHONE_NEW para isolamento de testes."""
		for lead in frappe.get_all(
			"CRM Lead", filters={"mobile_no": PHONE_NEW}, pluck="name"
		):
			frappe.db.delete(
				"Communication",
				{"reference_doctype": "CRM Lead", "reference_name": lead},
			)
			frappe.db.delete(
				"CRM Call Log",
				{"reference_doctype": "CRM Lead", "reference_docname": lead},
			)
			frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
		for cp in frappe.get_all(
			"Contact Phone", filters={"phone": PHONE_NEW}, pluck="parent"
		):
			try:
				frappe.delete_doc("Contact", cp, ignore_permissions=True, force=True)
			except Exception:
				pass
		for name in frappe.get_all("Patient", filters={"mobile": PHONE_NEW}, pluck="name"):
			frappe.delete_doc("Patient", name, ignore_permissions=True, force=True)
		frappe.db.commit()

	def _make_lead(self, phone: str, **extra) -> str:
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": extra.pop("first_name", "Lead"),
				"last_name": extra.pop("last_name", "Teste"),
				"email": extra.pop("email", None),
				"mobile_no": phone,
				"phone": phone,
				"source_channel": "WhatsApp",
				**extra,
			}
		).insert(ignore_permissions=True)
		return lead.name

	# ---------- search_patients ----------

	def test_search_by_first_name(self):
		results = patient_api.search_patients(query="Pedro", limit=10)
		names = [r.name for r in results]
		self.assertIn(self.existing_patient, names)

	def test_search_by_mobile(self):
		results = patient_api.search_patients(query=PHONE_EXISTING, limit=10)
		names = [r.name for r in results]
		self.assertIn(self.existing_patient, names)

	def test_search_empty_query_returns_empty(self):
		self.assertEqual(patient_api.search_patients(query="", limit=10), [])
		self.assertEqual(patient_api.search_patients(query="  ", limit=10), [])

	def test_search_respects_limit(self):
		results = patient_api.search_patients(query="e", limit=2)
		self.assertLessEqual(len(results), 2)

	# ---------- link_lead_to_patient ----------

	def test_link_lead_to_existing_patient(self):
		lead = self._make_lead(PHONE_NEW)
		result = patient_api.link_lead_to_patient(lead=lead, patient=self.existing_patient)
		self.assertTrue(result["ok"])
		self.assertEqual(result["patient"], self.existing_patient)
		self.assertEqual(
			frappe.db.get_value("CRM Lead", lead, "patient"), self.existing_patient
		)

	def test_link_creates_dynamic_link_on_contact(self):
		lead = self._make_lead(PHONE_NEW)
		patient_api.link_lead_to_patient(lead=lead, patient=self.existing_patient)
		# Contato criado pelo ensure_contact dentro do endpoint
		contact = frappe.get_all(
			"Contact Phone", filters={"phone": PHONE_NEW}, pluck="parent", limit=1
		)
		self.assertTrue(contact)
		linked = frappe.db.exists(
			"Dynamic Link",
			{
				"parent": contact[0],
				"parenttype": "Contact",
				"link_doctype": "Patient",
				"link_name": self.existing_patient,
			},
		)
		self.assertTrue(linked)

	def test_link_blocks_when_already_linked_without_force(self):
		lead = self._make_lead(PHONE_NEW, patient=self.existing_patient)
		with self.assertRaises(frappe.ValidationError):
			patient_api.link_lead_to_patient(lead=lead, patient=self.duplicate_patient)
		# Patient não foi sobrescrito
		self.assertEqual(
			frappe.db.get_value("CRM Lead", lead, "patient"), self.existing_patient
		)

	def test_link_force_overwrites(self):
		lead = self._make_lead(PHONE_NEW, patient=self.existing_patient)
		result = patient_api.link_lead_to_patient(
			lead=lead, patient=self.duplicate_patient, force=1
		)
		self.assertEqual(result["patient"], self.duplicate_patient)
		self.assertEqual(result["previous_patient"], self.existing_patient)
		self.assertEqual(
			frappe.db.get_value("CRM Lead", lead, "patient"), self.duplicate_patient
		)

	def test_link_idempotent_when_already_correct(self):
		lead = self._make_lead(PHONE_NEW, patient=self.existing_patient)
		result = patient_api.link_lead_to_patient(lead=lead, patient=self.existing_patient)
		self.assertTrue(result["ok"])
		self.assertIsNone(result["previous_patient"])

	def test_link_rejects_nonexistent_patient(self):
		lead = self._make_lead(PHONE_NEW)
		with self.assertRaises(frappe.ValidationError):
			patient_api.link_lead_to_patient(lead=lead, patient="Patient/Inexistente")

	def test_link_backfills_existing_communications(self):
		lead = self._make_lead(PHONE_NEW)
		# Communication criada antes do link (sem patient via doc_event)
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "WhatsApp",
				"sent_or_received": "Received",
				"content": "antes do link",
				"reference_doctype": "CRM Lead",
				"reference_name": lead,
				"twilio_message_sid": "SM_backfill_link_test",
				"whatsapp_direction": "inbound",
			}
		).insert(ignore_permissions=True)
		# Sem timeline_link para self.existing_patient ainda
		self.assertFalse(
			frappe.db.exists(
				"Communication Link",
				{
					"parent": comm.name,
					"link_doctype": "Patient",
					"link_name": self.existing_patient,
				},
			)
		)

		result = patient_api.link_lead_to_patient(lead=lead, patient=self.existing_patient)
		self.assertGreaterEqual(result["backfilled"]["communications"], 1)
		self.assertTrue(
			frappe.db.exists(
				"Communication Link",
				{
					"parent": comm.name,
					"link_doctype": "Patient",
					"link_name": self.existing_patient,
				},
			)
		)

	# ---------- create_patient_from_lead ----------

	def test_create_patient_from_lead_basic(self):
		lead = self._make_lead(
			PHONE_NEW, first_name="Nova", last_name="Paciente", email="nova@example.com"
		)
		result = patient_api.create_patient_from_lead(lead=lead, sex="Female")
		self.assertTrue(result["ok"])
		patient_name = result["patient"]
		patient = frappe.get_doc("Patient", patient_name)
		self.assertEqual(patient.first_name, "Nova")
		self.assertEqual(patient.last_name, "Paciente")
		self.assertEqual(patient.mobile, PHONE_NEW)
		self.assertEqual(patient.sex, "Female")
		self.assertEqual(patient.email, "nova@example.com")
		self.assertEqual(frappe.db.get_value("CRM Lead", lead, "patient"), patient_name)

	def test_create_patient_with_overrides(self):
		lead = self._make_lead(PHONE_NEW, first_name="Maria")
		result = patient_api.create_patient_from_lead(
			lead=lead,
			sex="Female",
			last_name="Sobrescrita",
			email="maria@override.com",
			dob="1990-05-15",
		)
		patient = frappe.get_doc("Patient", result["patient"])
		self.assertEqual(patient.last_name, "Sobrescrita")
		self.assertEqual(patient.email, "maria@override.com")
		self.assertEqual(str(patient.dob), "1990-05-15")

	def test_create_blocks_when_lead_already_linked(self):
		lead = self._make_lead(PHONE_NEW, patient=self.existing_patient)
		with self.assertRaises(frappe.ValidationError):
			patient_api.create_patient_from_lead(lead=lead, sex="Male")

	def test_create_blocks_when_mobile_duplicate(self):
		lead = self._make_lead(PHONE_DUPLICATE)
		with self.assertRaises(frappe.ValidationError):
			patient_api.create_patient_from_lead(lead=lead, sex="Male")

	def test_create_requires_phone(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Sem",
				"last_name": "Phone",
				"source_channel": "WhatsApp",
			}
		).insert(ignore_permissions=True)
		try:
			with self.assertRaises(frappe.ValidationError):
				patient_api.create_patient_from_lead(lead=lead.name, sex="Male")
		finally:
			frappe.delete_doc("CRM Lead", lead.name, ignore_permissions=True, force=True)

	def test_create_requires_sex(self):
		lead = self._make_lead(PHONE_NEW)
		with self.assertRaises(frappe.ValidationError):
			patient_api.create_patient_from_lead(lead=lead, sex="")
