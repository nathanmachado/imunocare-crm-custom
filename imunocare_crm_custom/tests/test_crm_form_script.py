from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom import custom_fields as cf

SCRIPT_NAME = cf.CRM_LEAD_FORM_SCRIPT_NAME


def _delete_script() -> None:
	if frappe.db.exists("CRM Form Script", SCRIPT_NAME):
		frappe.delete_doc("CRM Form Script", SCRIPT_NAME, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestCRMLeadFormScriptInstaller(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_delete_script()

	@classmethod
	def tearDownClass(cls):
		_delete_script()
		cf._ensure_crm_lead_form_script()
		super().tearDownClass()

	def test_creates_script_when_missing(self):
		self.assertFalse(frappe.db.exists("CRM Form Script", SCRIPT_NAME))
		cf._ensure_crm_lead_form_script()
		self.assertTrue(frappe.db.exists("CRM Form Script", SCRIPT_NAME))

		doc = frappe.get_doc("CRM Form Script", SCRIPT_NAME)
		self.assertEqual(doc.dt, "CRM Lead")
		self.assertEqual(doc.view, "Form")
		self.assertTrue(doc.enabled)
		self.assertIn("class CRMLead", doc.script)
		self.assertIn("whatsapp_window_status", doc.script)
		self.assertIn("voice_start", doc.script)
		self.assertIn("close_lead", doc.script)

	def test_is_idempotent_when_content_matches(self):
		cf._ensure_crm_lead_form_script()
		first_modified = frappe.db.get_value("CRM Form Script", SCRIPT_NAME, "modified")
		cf._ensure_crm_lead_form_script()
		second_modified = frappe.db.get_value("CRM Form Script", SCRIPT_NAME, "modified")
		self.assertEqual(first_modified, second_modified)

	def test_updates_script_when_content_diverges(self):
		cf._ensure_crm_lead_form_script()
		frappe.db.set_value(
			"CRM Form Script", SCRIPT_NAME, "script", "class CRMLead {} // stale"
		)
		frappe.db.commit()

		cf._ensure_crm_lead_form_script()
		body = frappe.db.get_value("CRM Form Script", SCRIPT_NAME, "script")
		self.assertIn("whatsapp_window_status", body)
		self.assertNotIn("// stale", body)
