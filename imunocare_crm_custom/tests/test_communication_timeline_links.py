from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.channels.base import (
	add_patient_timeline_link,
	communication_before_insert,
)

PHONE = "+5511944444444"


def _has_patient_link(comm_name: str, patient: str) -> bool:
	return bool(
		frappe.db.exists(
			"Communication Link",
			{"parent": comm_name, "link_doctype": "Patient", "link_name": patient},
		)
	)


def _count_patient_links(comm_name: str, patient: str) -> int:
	return frappe.db.count(
		"Communication Link",
		filters={"parent": comm_name, "link_doctype": "Patient", "link_name": patient},
	)


class TestCommunicationTimelineLinks(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._cleanup()

		cls.patient_name = (
			frappe.get_doc(
				{
					"doctype": "Patient",
					"first_name": "Tim",
					"last_name": "Linker",
					"mobile": PHONE,
					"sex": "Male",
					"invite_user": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		cls.lead_with_patient = (
			frappe.get_doc(
				{
					"doctype": "CRM Lead",
					"first_name": "Tim",
					"mobile_no": PHONE,
					"phone": PHONE,
					"source_channel": "WhatsApp",
					"patient": cls.patient_name,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		cls.lead_no_patient = (
			frappe.get_doc(
				{
					"doctype": "CRM Lead",
					"first_name": "Sem",
					"mobile_no": "+5511933333333",
					"phone": "+5511933333333",
					"source_channel": "WhatsApp",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls._cleanup()
		super().tearDownClass()

	@classmethod
	def _cleanup(cls):
		for lead in frappe.get_all(
			"CRM Lead", filters={"mobile_no": ("in", [PHONE, "+5511933333333"])}, pluck="name"
		):
			frappe.db.delete(
				"Communication", {"reference_doctype": "CRM Lead", "reference_name": lead}
			)
			frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
		for name in frappe.get_all("Patient", filters={"mobile": PHONE}, pluck="name"):
			frappe.delete_doc("Patient", name, ignore_permissions=True, force=True)
		frappe.db.commit()

	def _make_comm(self, lead: str, sid_suffix: str) -> str:
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "WhatsApp",
				"sent_or_received": "Received",
				"content": "hello",
				"reference_doctype": "CRM Lead",
				"reference_name": lead,
				"twilio_message_sid": f"SM_test_{sid_suffix}",
				"whatsapp_direction": "inbound",
			}
		).insert(ignore_permissions=True)
		return comm.name

	def test_doc_event_links_patient_when_lead_has_patient(self):
		name = self._make_comm(self.lead_with_patient, "doc_event_yes")
		self.assertTrue(_has_patient_link(name, self.patient_name))

	def test_doc_event_noop_when_lead_has_no_patient(self):
		name = self._make_comm(self.lead_no_patient, "doc_event_no")
		self.assertEqual(_count_patient_links(name, self.patient_name), 0)

	def test_helper_is_idempotent(self):
		name = self._make_comm(self.lead_with_patient, "idempotent")
		# já populado pelo doc_event; segunda chamada não deve duplicar
		added = add_patient_timeline_link(name, self.patient_name)
		self.assertFalse(added)
		self.assertEqual(_count_patient_links(name, self.patient_name), 1)

	def test_helper_returns_false_for_invalid_inputs(self):
		self.assertFalse(add_patient_timeline_link("", self.patient_name))
		self.assertFalse(add_patient_timeline_link("nonexistent-comm", self.patient_name))
		self.assertFalse(add_patient_timeline_link("any", None))
		self.assertFalse(add_patient_timeline_link("any", "Patient/Inexistente"))

	def test_doc_event_skips_non_crm_lead_reference(self):
		"""Communication referenciando outro doctype não dispara lookup de Patient."""
		# Cria Communication referenciando o próprio Patient — sem reference a CRM Lead
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Sent",
				"content": "test",
				"reference_doctype": "Patient",
				"reference_name": self.patient_name,
			}
		).insert(ignore_permissions=True)
		# Não deve haver vínculo extra para Patient via timeline_links (já é o reference principal)
		links = frappe.db.count(
			"Communication Link",
			filters={"parent": comm.name, "link_doctype": "Patient"},
		)
		# 0 ou 1 dependendo do auto-link do Frappe — o que importa é que nosso hook não duplicou
		self.assertLessEqual(links, 1)

	def test_communication_before_insert_directly(self):
		"""Chama o hook diretamente sem inserir, validando lógica isolada."""
		doc = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "WhatsApp",
				"sent_or_received": "Received",
				"content": "direct",
				"reference_doctype": "CRM Lead",
				"reference_name": self.lead_with_patient,
				"twilio_message_sid": "SM_direct_call",
				"whatsapp_direction": "inbound",
			}
		)
		communication_before_insert(doc)
		patient_links = [
			lk for lk in (doc.timeline_links or []) if lk.link_doctype == "Patient"
		]
		self.assertEqual(len(patient_links), 1)
		self.assertEqual(patient_links[0].link_name, self.patient_name)
