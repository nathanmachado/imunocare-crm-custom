from __future__ import annotations

import frappe
from frappe import _

from imunocare_crm_custom.channels.base import (
	backfill_patient_links_for_lead,
	ensure_contact,
)
from imunocare_crm_custom.utils.phone import normalize_phone

SEARCH_LIMIT_MAX = 50
SEARCH_LIMIT_DEFAULT = 10


@frappe.whitelist()
def search_patients(query: str = "", limit: int | str = SEARCH_LIMIT_DEFAULT) -> list[dict]:
	"""Busca Patients por nome/mobile/email/name. Retorna até `limit` resultados.

	Para uso em autocomplete na UI de vinculação Lead→Patient.
	"""
	if not frappe.has_permission("Patient", "read"):
		frappe.throw(_("Sem permissão para consultar Patient."), frappe.PermissionError)

	q = (query or "").strip()
	if not q:
		return []

	try:
		limit_n = max(1, min(int(limit), SEARCH_LIMIT_MAX))
	except (TypeError, ValueError):
		limit_n = SEARCH_LIMIT_DEFAULT

	like = f"%{q}%"
	rows = frappe.db.sql(
		"""
		select name, first_name, last_name, mobile, phone, email
		from `tabPatient`
		where name like %s
		   or first_name like %s
		   or last_name like %s
		   or mobile like %s
		   or phone like %s
		   or email like %s
		order by modified desc
		limit %s
		""",
		(like, like, like, like, like, like, limit_n),
		as_dict=True,
	)
	return rows


@frappe.whitelist(methods=["POST"])
def link_lead_to_patient(lead: str, patient: str, force: int | str = 0) -> dict:
	"""Vincula um Patient existente ao CRM Lead.

	- Bloqueia se Lead já tem outro Patient (a menos que `force=1`).
	- Garante Dynamic Link no Contact (Patient).
	- Faz backfill de Communications e CRM Call Logs já existentes do Lead.
	"""
	if not lead or not patient:
		frappe.throw(_("lead e patient são obrigatórios"))

	if not frappe.has_permission("CRM Lead", "write", doc=lead):
		frappe.throw(_("Sem permissão para editar este Lead."), frappe.PermissionError)
	if not frappe.db.exists("Patient", patient):
		frappe.throw(_("Patient {0} não existe.").format(patient))

	force_flag = str(force) in ("1", "true", "True")
	current = frappe.db.get_value("CRM Lead", lead, "patient")
	if current and current != patient and not force_flag:
		frappe.throw(
			_("Lead já está vinculado ao Patient {0}. Envie force=1 para sobrescrever.").format(
				current
			)
		)

	frappe.db.set_value("CRM Lead", lead, "patient", patient, update_modified=False)

	phone_raw = frappe.db.get_value("CRM Lead", lead, "mobile_no") or frappe.db.get_value(
		"CRM Lead", lead, "phone"
	)
	if phone_raw:
		e164 = normalize_phone(phone_raw)
		if e164:
			contact_name = ensure_contact(e164)
			_ensure_contact_patient_link(contact_name, patient)

	backfilled = backfill_patient_links_for_lead(lead, patient)

	return {
		"ok": True,
		"lead": lead,
		"patient": patient,
		"previous_patient": current if current and current != patient else None,
		"backfilled": backfilled,
	}


@frappe.whitelist(methods=["POST"])
def create_patient_from_lead(
	lead: str,
	sex: str,
	dob: str | None = None,
	last_name: str | None = None,
	email: str | None = None,
) -> dict:
	"""Cria um novo Patient a partir do CRM Lead e o vincula.

	- Falha se Lead já tem Patient vinculado (use link_lead_to_patient com force=1).
	- Falha se já existir Patient com mesmo `mobile` (sugerindo link em vez de criar).
	- Herda first_name/email/mobile do Lead; permite override de `last_name`/`email`/`dob`.
	"""
	if not lead or not sex:
		frappe.throw(_("lead e sex são obrigatórios"))

	if not frappe.has_permission("CRM Lead", "write", doc=lead):
		frappe.throw(_("Sem permissão para editar este Lead."), frappe.PermissionError)
	if not frappe.has_permission("Patient", "create"):
		frappe.throw(_("Sem permissão para criar Patient."), frappe.PermissionError)

	lead_doc = frappe.get_doc("CRM Lead", lead)
	if lead_doc.patient:
		frappe.throw(
			_("Lead já está vinculado ao Patient {0}.").format(lead_doc.patient)
		)

	mobile = normalize_phone(lead_doc.mobile_no or lead_doc.phone or "")
	if not mobile:
		frappe.throw(_("Lead {0} não possui telefone válido para criar Patient.").format(lead))

	duplicate = frappe.db.get_value("Patient", {"mobile": mobile}, "name")
	if duplicate:
		frappe.throw(
			_("Já existe Patient {0} com mobile {1}. Use link_lead_to_patient.").format(
				duplicate, mobile
			)
		)

	first_name = (lead_doc.first_name or "").strip()
	last_name_val = (last_name or lead_doc.last_name or "").strip()
	if not first_name and not last_name_val:
		frappe.throw(_("Lead sem first_name/last_name — informe last_name no payload."))

	patient_payload = {
		"doctype": "Patient",
		"first_name": first_name or last_name_val,
		"last_name": last_name_val if first_name else "",
		"mobile": mobile,
		"sex": sex,
		"invite_user": 0,
	}
	email_val = (email or lead_doc.email or "").strip()
	if email_val:
		patient_payload["email"] = email_val
	if dob:
		patient_payload["dob"] = dob

	patient_doc = frappe.get_doc(patient_payload).insert()

	frappe.db.set_value("CRM Lead", lead, "patient", patient_doc.name, update_modified=False)

	contact_name = ensure_contact(mobile)
	_ensure_contact_patient_link(contact_name, patient_doc.name)

	backfilled = backfill_patient_links_for_lead(lead, patient_doc.name)

	return {
		"ok": True,
		"lead": lead,
		"patient": patient_doc.name,
		"backfilled": backfilled,
	}


def _ensure_contact_patient_link(contact_name: str, patient_name: str) -> None:
	"""Garante uma entrada Dynamic Link Contact→Patient. Idempotente."""
	if frappe.db.exists(
		"Dynamic Link",
		{
			"parent": contact_name,
			"parenttype": "Contact",
			"link_doctype": "Patient",
			"link_name": patient_name,
		},
	):
		return
	contact = frappe.get_doc("Contact", contact_name)
	contact.append("links", {"link_doctype": "Patient", "link_name": patient_name})
	contact.save(ignore_permissions=True)
