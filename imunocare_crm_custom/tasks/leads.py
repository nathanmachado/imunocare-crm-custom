from __future__ import annotations

import frappe
from frappe.desk.doctype.tag.tag import DocTags
from frappe.utils import add_to_date, now_datetime

INACTIVE_THRESHOLD_HOURS = 48
INACTIVE_TAG = "Inativo"
OPEN_STATUS_TYPES = ("Open", "Ongoing")


def tag_inactive_leads() -> dict:
	"""Varre CRM Leads em aberto com last_contact_at > 48h, aplica tag + ToDo ao atendente.

	Idempotente: pula leads já tagueados (inativo_tagged_at preenchido).
	Retorna dict com contagens para observabilidade.
	"""
	cutoff = add_to_date(now_datetime(), hours=-INACTIVE_THRESHOLD_HOURS)
	open_statuses = frappe.get_all(
		"CRM Lead Status",
		filters={"type": ("in", OPEN_STATUS_TYPES)},
		pluck="name",
	)
	if not open_statuses:
		return {"scanned": 0, "tagged": 0, "errors": 0}

	candidates = frappe.get_all(
		"CRM Lead",
		filters={
			"status": ("in", open_statuses),
			"last_contact_at": ("<=", cutoff),
			"inativo_tagged_at": ("is", "not set"),
		},
		fields=["name"],
	)

	tagged = 0
	errors = 0
	for row in candidates:
		try:
			_tag_one(row.name)
			tagged += 1
		except Exception:
			errors += 1
			frappe.log_error(
				title=f"tag_inactive_leads falhou (lead={row.name})",
				message=frappe.get_traceback(),
			)
	return {"scanned": len(candidates), "tagged": tagged, "errors": errors}


def _tag_one(lead: str) -> None:
	DocTags("CRM Lead").add(lead, INACTIVE_TAG)

	assignee = _current_assignee(lead)
	if assignee:
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": assignee,
				"reference_type": "CRM Lead",
				"reference_name": lead,
				"description": f"Lead inativo há mais de {INACTIVE_THRESHOLD_HOURS}h — retomar contato.",
				"priority": "Medium",
				"status": "Open",
			}
		).insert(ignore_permissions=True)

	frappe.db.set_value(
		"CRM Lead", lead, "inativo_tagged_at", now_datetime(), update_modified=False
	)


def _current_assignee(lead: str) -> str | None:
	todos = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": "CRM Lead",
			"reference_name": lead,
			"status": "Open",
		},
		fields=["allocated_to"],
		order_by="creation desc",
		limit=1,
	)
	return todos[0].allocated_to if todos and todos[0].allocated_to else None
