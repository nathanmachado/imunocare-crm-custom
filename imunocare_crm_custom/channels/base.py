from __future__ import annotations

from typing import Literal

import frappe

from imunocare_crm_custom.utils.phone import normalize_phone

Channel = Literal["WhatsApp", "Voice"]

OPEN_LEAD_FILTER = {"converted": 0}


def resolve_patient(phone: str) -> str | None:
	"""Retorna o nome do Patient com este telefone, se existir (via Contact ou direto)."""
	e164 = normalize_phone(phone)
	if not e164:
		return None

	# Via Contact.links (Dynamic Link)
	patient = frappe.db.sql(
		"""
		select dl.link_name
		from `tabDynamic Link` dl
		inner join `tabContact Phone` cp on cp.parent = dl.parent
		where dl.parenttype = 'Contact' and dl.link_doctype = 'Patient' and cp.phone = %s
		limit 1
		""",
		(e164,),
	)
	if patient:
		return patient[0][0]

	direct = frappe.get_all("Patient", filters={"mobile": e164}, pluck="name", limit=1)
	if direct:
		return direct[0]
	direct = frappe.get_all("Patient", filters={"phone": e164}, pluck="name", limit=1)
	if direct:
		return direct[0]

	return None


def resolve_contact(phone: str) -> str | None:
	"""Retorna o nome do Contact com este telefone, se existir."""
	e164 = normalize_phone(phone)
	if not e164:
		return None

	via_child = frappe.get_all(
		"Contact Phone",
		filters={"phone": e164, "parenttype": "Contact"},
		pluck="parent",
		limit=1,
	)
	if via_child:
		return via_child[0]

	direct = frappe.get_all("Contact", filters={"mobile_no": e164}, pluck="name", limit=1)
	if direct:
		return direct[0]

	return None


def ensure_contact(phone: str, display_name: str | None = None) -> str:
	"""Retorna nome do Contact; cria se não existir."""
	existing = resolve_contact(phone)
	if existing:
		return existing

	e164 = normalize_phone(phone)
	doc = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": (display_name or e164 or "Desconhecido").strip(),
			"mobile_no": e164,
			"phone_nos": [{"phone": e164, "is_primary_mobile_no": 1}],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _find_open_lead(e164: str, patient: str | None) -> str | None:
	filters = dict(OPEN_LEAD_FILTER)
	if patient:
		filters["patient"] = patient
		found = frappe.get_all("CRM Lead", filters=filters, pluck="name", order_by="creation desc", limit=1)
		if found:
			return found[0]
	# Por telefone
	filters = dict(OPEN_LEAD_FILTER)
	filters["mobile_no"] = e164
	found = frappe.get_all("CRM Lead", filters=filters, pluck="name", order_by="creation desc", limit=1)
	return found[0] if found else None


def get_or_create_lead(
	phone: str,
	channel: Channel,
	display_name: str | None = None,
) -> str:
	"""Resolve/cria Contact, Patient (se existir) e Lead aberto. Retorna o nome do Lead."""
	e164 = normalize_phone(phone)
	if not e164:
		frappe.throw(f"Telefone inválido: {phone!r}")

	patient = resolve_patient(e164)
	ensure_contact(e164, display_name=display_name)

	now = frappe.utils.now_datetime()

	existing_lead = _find_open_lead(e164, patient)
	if existing_lead:
		frappe.db.set_value(
			"CRM Lead",
			existing_lead,
			{"last_contact_at": now},
			update_modified=False,
		)
		return existing_lead

	lead = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": display_name or e164,
			"mobile_no": e164,
			"phone": e164,
			"source_channel": channel,
			"patient": patient,
			"first_contact_at": now,
			"last_contact_at": now,
		}
	)
	lead.insert(ignore_permissions=True)
	return lead.name


def apply_assignment(lead_name: str) -> str | None:
	"""Stub: atribuição automática via Assignment Rule é aplicada pelo core.

	Esta função retorna o User atualmente atribuído (se houver) — chamada após o Assignment
	Rule nativo do Frappe ter rodado. Implementação real em MVP-08.
	"""
	assignments = frappe.db.get_all(
		"ToDo",
		filters={"reference_type": "CRM Lead", "reference_name": lead_name, "status": "Open"},
		fields=["allocated_to"],
		limit=1,
	)
	return assignments[0].allocated_to if assignments else None
