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


def add_patient_timeline_link(comm_name: str, patient: str | None) -> bool:
	"""Garante que a Communication tenha um `timeline_link` para o Patient.

	Idempotente: não duplica vínculo já existente. Retorna True se adicionou,
	False caso contrário (já existia, patient inválido, ou comm não encontrada).
	"""
	if not comm_name or not patient:
		return False
	if not frappe.db.exists("Communication", comm_name):
		return False
	if not frappe.db.exists("Patient", patient):
		return False
	if frappe.db.exists(
		"Communication Link",
		{"parent": comm_name, "link_doctype": "Patient", "link_name": patient},
	):
		return False
	comm = frappe.get_doc("Communication", comm_name)
	comm.append("timeline_links", {"link_doctype": "Patient", "link_name": patient})
	comm.save(ignore_permissions=True)
	return True


def communication_before_insert(doc, method=None) -> None:
	"""doc_event: ao inserir Communication referenciando CRM Lead com paciente,
	popula `timeline_links` para o Patient automaticamente.
	"""
	if doc.reference_doctype != "CRM Lead" or not doc.reference_name:
		return
	patient = frappe.db.get_value("CRM Lead", doc.reference_name, "patient")
	if not patient:
		return
	if not frappe.db.exists("Patient", patient):
		return
	for link in doc.get("timeline_links") or []:
		if link.get("link_doctype") == "Patient" and link.get("link_name") == patient:
			return
	doc.append("timeline_links", {"link_doctype": "Patient", "link_name": patient})


def backfill_patient_links_for_lead(lead: str, patient: str) -> dict:
	"""Atualiza Communications e CRM Call Logs do Lead para referenciar o Patient.

	- Communications: adiciona `timeline_link` para Patient quando faltar.
	- CRM Call Logs: seta o campo `patient` quando vazio.

	Idempotente. Retorna {"communications": N, "call_logs": M} com a quantidade
	de registros efetivamente atualizados.
	"""
	if not lead or not patient:
		return {"communications": 0, "call_logs": 0}
	if not frappe.db.exists("Patient", patient):
		return {"communications": 0, "call_logs": 0}

	comm_count = 0
	for comm_name in frappe.get_all(
		"Communication",
		filters={"reference_doctype": "CRM Lead", "reference_name": lead},
		pluck="name",
	):
		try:
			if add_patient_timeline_link(comm_name, patient):
				comm_count += 1
		except Exception:
			frappe.log_error(
				title=f"backfill timeline_link Patient (comm={comm_name}, patient={patient})",
				message=frappe.get_traceback(),
			)

	log_count = 0
	for log_name in frappe.get_all(
		"CRM Call Log",
		filters={
			"reference_doctype": "CRM Lead",
			"reference_docname": lead,
			"patient": ("in", ["", None]),
		},
		pluck="name",
	):
		try:
			frappe.db.set_value(
				"CRM Call Log", log_name, "patient", patient, update_modified=False
			)
			log_count += 1
		except Exception:
			frappe.log_error(
				title=f"backfill patient (call_log={log_name}, patient={patient})",
				message=frappe.get_traceback(),
			)

	return {"communications": comm_count, "call_logs": log_count}


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


ATTENDANT_ROLE = "Imunocare Atendente"


def apply_assignment(lead_name: str) -> str | None:
	"""Atribui Lead a um atendente ativo via round-robin.

	Retorna o User atribuído. Idempotente: se já há ToDo aberto, retorna o allocated_to.
	Se não há nenhum atendente ativo com role `Imunocare Atendente`, retorna None.
	"""
	existing = _get_existing_assignee(lead_name)
	if existing:
		return existing

	user = _pick_next_agent()
	if not user:
		return None

	from frappe.desk.form.assign_to import add

	try:
		add(
			{
				"assign_to": [user],
				"doctype": "CRM Lead",
				"name": lead_name,
				"description": "Atribuição automática Imunocare (round-robin)",
			}
		)
	except Exception:
		frappe.log_error(
			title=f"apply_assignment falhou (lead={lead_name}, user={user})",
			message=frappe.get_traceback(),
		)
		return None
	return user


def _get_existing_assignee(lead_name: str) -> str | None:
	assignments = frappe.db.get_all(
		"ToDo",
		filters={"reference_type": "CRM Lead", "reference_name": lead_name, "status": "Open"},
		fields=["allocated_to"],
		limit=1,
	)
	return assignments[0].allocated_to if assignments else None


def _pick_next_agent() -> str | None:
	"""Retorna o atendente menos recentemente atribuído (round-robin por last-assigned-time)."""
	candidates = frappe.db.sql(
		"""
		select hr.parent as user
		from `tabHas Role` hr
		inner join `tabUser` u on u.name = hr.parent
		where hr.role = %s
		  and hr.parenttype = 'User'
		  and u.enabled = 1
		""",
		(ATTENDANT_ROLE,),
		as_dict=True,
	)
	if not candidates:
		return None

	user_list = [c.user for c in candidates]
	# Última atribuição de ToDo (CRM Lead) por usuário
	last_per_user: dict[str, str] = {u: "" for u in user_list}
	rows = frappe.db.sql(
		"""
		select allocated_to, max(creation) as last_at
		from `tabToDo`
		where reference_type = 'CRM Lead'
		  and allocated_to in %(users)s
		group by allocated_to
		""",
		{"users": tuple(user_list)},
		as_dict=True,
	)
	for r in rows:
		last_per_user[r.allocated_to] = str(r.last_at or "")

	# Prioriza quem nunca recebeu; depois least-recent
	return min(user_list, key=lambda u: (last_per_user[u] or "", u))
