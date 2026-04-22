from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.channels import base as channels_base

ROLE = "Imunocare Atendente"
AGENTS = [
	"voice-rr-1@example.com",
	"voice-rr-2@example.com",
	"voice-rr-3@example.com",
]


def _cleanup() -> None:
	for u in AGENTS:
		if frappe.db.exists("User", u):
			# Clean ToDos addressed to this user
			for t in frappe.get_all(
				"ToDo", filters={"allocated_to": u}, pluck="name"
			):
				frappe.delete_doc("ToDo", t, ignore_permissions=True, force=True)
			frappe.delete_doc("User", u, ignore_permissions=True, force=True)
	for lead in frappe.get_all(
		"CRM Lead", filters={"first_name": ("like", "Assignment Test%")}, pluck="name"
	):
		for t in frappe.get_all(
			"ToDo", filters={"reference_type": "CRM Lead", "reference_name": lead}, pluck="name"
		):
			frappe.delete_doc("ToDo", t, ignore_permissions=True, force=True)
		frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
	frappe.db.commit()


def _mk_user(email: str, enabled: int = 1, with_role: bool = True) -> None:
	if frappe.db.exists("User", email):
		return
	doc = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"enabled": enabled,
		}
	)
	if with_role:
		doc.append("roles", {"role": ROLE})
	doc.insert(ignore_permissions=True)


def _mk_lead(suffix: str) -> str:
	lead = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": f"Assignment Test {suffix}",
			"source_channel": "Voice",
		}
	).insert(ignore_permissions=True)
	return lead.name


class TestAssignment(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_cleanup()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		super().tearDownClass()

	def setUp(self):
		_cleanup()

	def test_no_agents_returns_none(self):
		lead = _mk_lead("noagents")
		self.assertIsNone(channels_base.apply_assignment(lead))

	def test_single_agent_gets_all_assignments(self):
		_mk_user(AGENTS[0])
		for i in range(3):
			lead = _mk_lead(f"single-{i}")
			self.assertEqual(channels_base.apply_assignment(lead), AGENTS[0])

	def test_round_robin_distributes_evenly(self):
		for u in AGENTS:
			_mk_user(u)

		counts = {u: 0 for u in AGENTS}
		for i in range(9):
			lead = _mk_lead(f"rr-{i}")
			assignee = channels_base.apply_assignment(lead)
			self.assertIn(assignee, AGENTS)
			counts[assignee] += 1

		# 9 leads / 3 agents → 3 cada
		self.assertEqual(sorted(counts.values()), [3, 3, 3])

	def test_disabled_agent_is_skipped(self):
		_mk_user(AGENTS[0], enabled=0)
		_mk_user(AGENTS[1], enabled=1)
		for i in range(4):
			lead = _mk_lead(f"dis-{i}")
			self.assertEqual(channels_base.apply_assignment(lead), AGENTS[1])

	def test_idempotent_second_call_returns_same_user(self):
		_mk_user(AGENTS[0])
		_mk_user(AGENTS[1])
		lead = _mk_lead("idem")
		first = channels_base.apply_assignment(lead)
		second = channels_base.apply_assignment(lead)
		self.assertEqual(first, second)
		# Só 1 ToDo aberto
		open_todos = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "CRM Lead",
				"reference_name": lead,
				"status": "Open",
			},
			pluck="name",
		)
		self.assertEqual(len(open_todos), 1)

	def test_user_without_role_is_not_picked(self):
		_mk_user(AGENTS[0], with_role=False)
		_mk_user(AGENTS[1])
		lead = _mk_lead("norole")
		self.assertEqual(channels_base.apply_assignment(lead), AGENTS[1])
