from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from imunocare_crm_custom.twilio_integration.client import get_client

APPROVAL_MAP = {
	"approved": "Approved",
	"rejected": "Rejected",
	"paused": "Paused",
	"pending": "Pending",
	"received": "Pending",
	"unsubmitted": "Pending",
}


def sync_message_templates_approval() -> None:
	"""Sincroniza approval_status dos Message Templates com Twilio Content API."""
	templates = frappe.get_all(
		"Message Template",
		filters={"twilio_content_sid": ("is", "set")},
		pluck="name",
	)
	if not templates:
		return

	client = get_client()
	for name in templates:
		try:
			_sync_one(client, name)
		except Exception:
			frappe.log_error(
				title=f"Twilio Content sync falhou (template={name})",
				message=frappe.get_traceback(),
			)


def _sync_one(client, template_name: str) -> None:
	doc = frappe.get_doc("Message Template", template_name)
	approval = client.content.v1.content(doc.twilio_content_sid).approval_fetch().fetch()
	raw_status = getattr(approval, "status", None) or ""
	mapped = APPROVAL_MAP.get(raw_status.lower(), "Pending")
	frappe.db.set_value(
		"Message Template",
		template_name,
		{"approval_status": mapped, "last_sync_at": now_datetime()},
		update_modified=False,
	)
