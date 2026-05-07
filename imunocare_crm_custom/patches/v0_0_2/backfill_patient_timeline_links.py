from __future__ import annotations

import frappe

from imunocare_crm_custom.channels.base import backfill_patient_links_for_lead


def execute() -> None:
	"""Backfill de Communications e CRM Call Logs para apontar para o Patient.

	Para cada CRM Lead com `patient` definido:
	  - Adiciona `timeline_link` para Patient nas Communications referenciadas.
	  - Seta `patient` em CRM Call Logs referenciados que estavam vazios.

	Idempotente — pode ser executado múltiplas vezes sem efeitos colaterais.
	"""
	leads = frappe.get_all(
		"CRM Lead",
		filters={"patient": ("is", "set")},
		fields=["name", "patient"],
	)
	for row in leads:
		if not row.patient:
			continue
		try:
			backfill_patient_links_for_lead(row.name, row.patient)
		except Exception:
			frappe.log_error(
				title=f"v0_0_2 backfill_patient_timeline_links (lead={row.name})",
				message=frappe.get_traceback(),
			)
	frappe.db.commit()
