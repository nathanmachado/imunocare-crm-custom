from __future__ import annotations

import frappe

from imunocare_crm_custom.channels.base import resolve_patient

MISSED_STATUSES = {"No Answer", "Failed", "Busy"}


def after_insert(doc, method=None) -> None:
	"""Vincula Patient ao CRM Call Log com base no número do contato."""
	if doc.get("patient"):
		return
	contact_phone = doc.get("from") if doc.get("type") == "Incoming" else doc.get("to")
	if not contact_phone:
		return
	patient = resolve_patient(contact_phone)
	if not patient:
		return
	doc.db_set("patient", patient, update_modified=False)


def on_update(doc, method=None) -> None:
	"""Cria ToDo de retorno quando a chamada transita para missed."""
	new_status = doc.get("status")
	if new_status not in MISSED_STATUSES:
		return
	before = doc.get_doc_before_save()
	if before and before.get("status") == new_status:
		return

	agente = doc.get("receiver") if doc.get("type") == "Incoming" else doc.get("caller")
	if not agente:
		return

	if frappe.db.exists(
		"ToDo",
		{
			"reference_type": "CRM Call Log",
			"reference_name": doc.name,
			"status": "Open",
		},
	):
		return

	contact_phone = doc.get("from") if doc.get("type") == "Incoming" else doc.get("to")
	patient = doc.get("patient")
	if patient:
		description = (
			f"Retornar chamada perdida — paciente {patient}, número {contact_phone} "
			f"(status: {new_status})"
		)
	else:
		description = f"Retornar chamada perdida de {contact_phone} (status: {new_status})"

	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": agente,
			"reference_type": "CRM Call Log",
			"reference_name": doc.name,
			"description": description,
			"priority": "High",
			"date": frappe.utils.today(),
		}
	).insert(ignore_permissions=True)
