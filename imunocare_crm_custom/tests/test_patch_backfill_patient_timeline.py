from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.patches.v0_0_2 import backfill_patient_timeline_links

PHONE = "+5511988888888"


def _cleanup() -> None:
	for lead in frappe.get_all("CRM Lead", filters={"mobile_no": PHONE}, pluck="name"):
		frappe.db.delete(
			"Communication", {"reference_doctype": "CRM Lead", "reference_name": lead}
		)
		frappe.db.delete(
			"CRM Call Log", {"reference_doctype": "CRM Lead", "reference_docname": lead}
		)
		frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
	for name in frappe.get_all("Patient", filters={"mobile": PHONE}, pluck="name"):
		frappe.delete_doc("Patient", name, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestPatchBackfillPatientTimelineLinks(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_cleanup()

		cls.patient_name = (
			frappe.get_doc(
				{
					"doctype": "Patient",
					"first_name": "Patch",
					"last_name": "Target",
					"mobile": PHONE,
					"sex": "Female",
					"invite_user": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		# Lead com patient já vinculado
		cls.lead_name = (
			frappe.get_doc(
				{
					"doctype": "CRM Lead",
					"first_name": "Patch",
					"mobile_no": PHONE,
					"phone": PHONE,
					"source_channel": "WhatsApp",
					"patient": cls.patient_name,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		# Communication SEM timeline_link para Patient (simulando histórico antes do MVP-13)
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "WhatsApp",
				"sent_or_received": "Received",
				"content": "comm pré-MVP13",
				"reference_doctype": "CRM Lead",
				"reference_name": cls.lead_name,
				"twilio_message_sid": "SM_patch_legacy",
				"whatsapp_direction": "inbound",
			}
		).insert(ignore_permissions=True)
		# Remove timeline_link se o doc_event tiver populado (force estado pré-MVP-13)
		frappe.db.delete(
			"Communication Link",
			{"parent": comm.name, "link_doctype": "Patient", "link_name": cls.patient_name},
		)
		cls.comm_name = comm.name

		# CRM Call Log SEM patient (simulando histórico)
		log = frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"id": "CA_patch_legacy",
				"from": PHONE,
				"to": "+5511900000001",
				"type": "Incoming",
				"status": "Completed",
				"start_time": frappe.utils.now_datetime(),
				"telephony_medium": "Twilio",
				"medium": "Voice",
				"reference_doctype": "CRM Lead",
				"reference_docname": cls.lead_name,
			}
		).insert(ignore_permissions=True)
		# Garante que patient está vazio
		frappe.db.set_value("CRM Call Log", log.name, "patient", None, update_modified=False)
		cls.log_name = log.name

		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		super().tearDownClass()

	def test_patch_backfills_communication_and_call_log(self):
		# Estado pré-patch: vínculo ausente
		self.assertFalse(
			frappe.db.exists(
				"Communication Link",
				{
					"parent": self.comm_name,
					"link_doctype": "Patient",
					"link_name": self.patient_name,
				},
			)
		)
		self.assertIsNone(
			frappe.db.get_value("CRM Call Log", self.log_name, "patient") or None
		)

		backfill_patient_timeline_links.execute()

		# Comm agora tem timeline_link para Patient
		self.assertTrue(
			frappe.db.exists(
				"Communication Link",
				{
					"parent": self.comm_name,
					"link_doctype": "Patient",
					"link_name": self.patient_name,
				},
			)
		)
		# Call Log agora tem patient setado
		self.assertEqual(
			frappe.db.get_value("CRM Call Log", self.log_name, "patient"),
			self.patient_name,
		)

	def test_patch_is_idempotent(self):
		backfill_patient_timeline_links.execute()
		count_before = frappe.db.count(
			"Communication Link",
			filters={
				"parent": self.comm_name,
				"link_doctype": "Patient",
				"link_name": self.patient_name,
			},
		)
		backfill_patient_timeline_links.execute()
		count_after = frappe.db.count(
			"Communication Link",
			filters={
				"parent": self.comm_name,
				"link_doctype": "Patient",
				"link_name": self.patient_name,
			},
		)
		self.assertEqual(count_before, count_after)
		self.assertEqual(count_after, 1)
