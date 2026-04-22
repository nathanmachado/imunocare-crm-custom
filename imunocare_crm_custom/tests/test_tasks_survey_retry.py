from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from imunocare_crm_custom.tasks import survey_retry

PHONE_TEST = "+5511922220099"
AGENT_EMAIL = "survey-retry-agent@example.com"


def _cleanup() -> None:
	for qf in frappe.get_all("Quality Feedback", filters={"crm_lead": ("like", "%")}, pluck="name"):
		frappe.delete_doc("Quality Feedback", qf, ignore_permissions=True, force=True)
	for lead in frappe.get_all(
		"CRM Lead", filters={"first_name": ("like", "Retry Test%")}, pluck="name"
	):
		frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
	frappe.db.commit()


def _force_last_invite(lead: str, hours_ago: float) -> None:
	when = add_to_date(now_datetime(), hours=-hours_ago)
	frappe.db.set_value(
		"CRM Lead", lead, "survey_last_invite_at", when, update_modified=False
	)
	frappe.db.commit()


class TestRetrySurveyInvites(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_cleanup()
		if not frappe.db.exists("User", AGENT_EMAIL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": AGENT_EMAIL,
					"first_name": "Retry",
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

	def _mk_closed_lead(self, suffix: str, count: int = 1) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": f"Retry Test {suffix}",
				"mobile_no": PHONE_TEST,
				"source_channel": "WhatsApp",
				"atendente_encerramento": AGENT_EMAIL,
				"avaliacao_enviada": 1,
				"survey_invite_count": count,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def test_resends_when_24h_elapsed_and_under_max(self):
		lead = self._mk_closed_lead("resend", count=1)
		_force_last_invite(lead, hours_ago=25)

		with patch.object(survey_retry, "_retry_one", return_value=True) as m:
			result = survey_retry.retry_survey_invites()

		m.assert_called_once_with(lead)
		self.assertEqual(result["resent"], 1)

	def test_skips_when_less_than_24h_elapsed(self):
		lead = self._mk_closed_lead("wait", count=1)
		_force_last_invite(lead, hours_ago=5)

		with patch.object(survey_retry, "_retry_one") as m:
			result = survey_retry.retry_survey_invites()

		m.assert_not_called()
		self.assertEqual(result["scanned"], 0)

	def test_skips_when_max_attempts_reached(self):
		lead = self._mk_closed_lead("max", count=2)
		_force_last_invite(lead, hours_ago=30)

		with patch.object(survey_retry, "_retry_one") as m:
			result = survey_retry.retry_survey_invites()

		m.assert_not_called()
		self.assertEqual(result["scanned"], 0)

	def test_skips_when_quality_feedback_exists(self):
		lead = self._mk_closed_lead("answered", count=1)
		_force_last_invite(lead, hours_ago=30)

		# Seed QF to simulate customer already responded
		frappe.get_doc(
			{
				"doctype": "Quality Feedback",
				"template": "Avaliação de Atendimento Imunocare",
				"document_type": "User",
				"document_name": AGENT_EMAIL,
				"crm_lead": lead,
				"parameters": [{"parameter": "Canal", "rating": "5"}],
			}
		).insert(ignore_permissions=True)

		with patch.object(survey_retry, "_retry_one") as m:
			result = survey_retry.retry_survey_invites()

		m.assert_not_called()
		self.assertEqual(result["scanned"], 0)

	def test_increments_counter_and_timestamp(self):
		lead = self._mk_closed_lead("inc", count=1)
		_force_last_invite(lead, hours_ago=30)

		with patch(
			"imunocare_crm_custom.api.survey._dispatch_invite", return_value=True
		):
			result = survey_retry.retry_survey_invites()

		self.assertEqual(result["resent"], 1)
		self.assertEqual(frappe.db.get_value("CRM Lead", lead, "survey_invite_count"), 2)
		self.assertIsNotNone(
			frappe.db.get_value("CRM Lead", lead, "survey_last_invite_at")
		)

	def test_open_lead_never_invited_is_scanned_if_closed(self):
		# Lead that was closed but never dispatched (count=0) and no prior timestamp
		lead = self._mk_closed_lead("first", count=0)

		with patch.object(survey_retry, "_retry_one", return_value=True) as m:
			result = survey_retry.retry_survey_invites()

		m.assert_called_once_with(lead)
		self.assertEqual(result["resent"], 1)
