from __future__ import annotations

import re

import frappe
from frappe.utils import add_to_date, now_datetime

from imunocare_crm_custom.twilio_integration.client import get_client, get_settings

RECORDING_SID_RE = re.compile(r"/Recordings/(RE[A-Za-z0-9]+)")


def purge_old_recordings() -> dict:
	"""Apaga gravações Twilio expiradas (LGPD).

	Usa `recording_retention_days` de Twilio Settings. Se ausente ou < 1, noop.
	Para cada CRM Call Log com recording_url antigo:
	  - extrai Recording SID da URL
	  - chama `client.recordings(sid).delete()`
	  - limpa recording_url do Call Log
	"""
	settings = get_settings()
	retention_days = int(settings.recording_retention_days or 0)
	if retention_days < 1:
		return {"scanned": 0, "purged": 0, "errors": 0, "skipped_reason": "retention_disabled"}

	cutoff = add_to_date(now_datetime(), days=-retention_days)
	candidates = frappe.get_all(
		"CRM Call Log",
		filters={
			"recording_url": ("is", "set"),
			"creation": ("<=", cutoff),
		},
		fields=["name", "recording_url"],
	)
	if not candidates:
		return {"scanned": 0, "purged": 0, "errors": 0}

	client = get_client()
	purged = 0
	errors = 0
	for row in candidates:
		try:
			sid = _extract_recording_sid(row.recording_url)
			if sid:
				client.recordings(sid).delete()
			frappe.db.set_value(
				"CRM Call Log", row.name, "recording_url", "", update_modified=False
			)
			purged += 1
		except Exception:
			errors += 1
			frappe.log_error(
				title=f"purge_old_recordings falhou (call={row.name})",
				message=frappe.get_traceback(),
			)
	return {"scanned": len(candidates), "purged": purged, "errors": errors}


def _extract_recording_sid(url: str) -> str | None:
	if not url:
		return None
	m = RECORDING_SID_RE.search(url)
	return m.group(1) if m else None
