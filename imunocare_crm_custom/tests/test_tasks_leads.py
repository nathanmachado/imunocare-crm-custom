from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from imunocare_crm_custom.tasks import leads as tasks_leads

PHONE_TEST = "+5511911110001"
AGENT_EMAIL = "tasks-leads-agent@example.com"


def _cleanup() -> None:
	for lead in frappe.get_all(
		"CRM Lead", filters={"first_name": ("like", "Inactive Test%")}, pluck="name"
	):
		for todo in frappe.get_all(
			"ToDo", filters={"reference_type": "CRM Lead", "reference_name": lead}, pluck="name"
		):
			frappe.delete_doc("ToDo", todo, ignore_permissions=True, force=True)
		frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
	frappe.db.commit()


def _force_last_contact(lead: str, hours_ago: float) -> None:
	when = add_to_date(now_datetime(), hours=-hours_ago)
	frappe.db.set_value("CRM Lead", lead, "last_contact_at", when, update_modified=False)
	frappe.db.commit()


class TestTagInactiveLeads(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_cleanup()
		if not frappe.db.exists("User", AGENT_EMAIL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": AGENT_EMAIL,
					"first_name": "Inactive",
					"last_name": "Agent",
					"send_welcome_email": 0,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		if frappe.db.exists("User", AGENT_EMAIL):
			frappe.delete_doc("User", AGENT_EMAIL, ignore_permissions=True, force=True)
		super().tearDownClass()

	def setUp(self):
		_cleanup()

	def _mk_lead(self, suffix: str, status: str = "New") -> str:
		doc = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": f"Inactive Test {suffix}",
				"mobile_no": PHONE_TEST,
				"status": status,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def test_lead_active_is_not_tagged(self):
		lead = self._mk_lead("active")
		_force_last_contact(lead, hours_ago=10)
		tasks_leads.tag_inactive_leads()
		self.assertFalse(frappe.db.get_value("CRM Lead", lead, "inativo_tagged_at"))

	def test_lead_inactive_48h_is_tagged(self):
		lead = self._mk_lead("inactive")
		_force_last_contact(lead, hours_ago=72)
		tasks_leads.tag_inactive_leads()
		tagged_at = frappe.db.get_value("CRM Lead", lead, "inativo_tagged_at")
		self.assertIsNotNone(tagged_at)
		tags = frappe.db.get_value("CRM Lead", lead, "_user_tags") or ""
		self.assertIn("Inativo", tags)

	def test_idempotent_second_run_does_not_retag(self):
		lead = self._mk_lead("idem")
		_force_last_contact(lead, hours_ago=72)
		tasks_leads.tag_inactive_leads()
		first_at = frappe.db.get_value("CRM Lead", lead, "inativo_tagged_at")
		tasks_leads.tag_inactive_leads()
		second_at = frappe.db.get_value("CRM Lead", lead, "inativo_tagged_at")
		self.assertEqual(first_at, second_at)

	def test_closed_lead_not_tagged(self):
		lead = self._mk_lead("closed", status="Converted")
		_force_last_contact(lead, hours_ago=72)
		tasks_leads.tag_inactive_leads()
		self.assertFalse(frappe.db.get_value("CRM Lead", lead, "inativo_tagged_at"))

	def test_creates_todo_for_current_assignee(self):
		lead = self._mk_lead("assigned")
		_force_last_contact(lead, hours_ago=72)
		# seed open ToDo as current assignment
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"reference_type": "CRM Lead",
				"reference_name": lead,
				"allocated_to": AGENT_EMAIL,
				"description": "Prior assignment",
				"status": "Open",
			}
		).insert(ignore_permissions=True)

		tasks_leads.tag_inactive_leads()

		todos = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "CRM Lead",
				"reference_name": lead,
				"allocated_to": AGENT_EMAIL,
				"description": ("like", "%inativo%"),
			},
		)
		self.assertGreaterEqual(len(todos), 1)
