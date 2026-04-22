from __future__ import annotations

import frappe
from twilio.rest import Client

from imunocare_crm_custom.twilio_integration.doctype.twilio_settings.twilio_settings import (
	TwilioSettings,
)


class TwilioNotConfigured(frappe.ValidationError):
	pass


def get_settings() -> TwilioSettings:
	return frappe.get_single("Twilio Settings")


def get_client() -> Client:
	settings = get_settings()
	if not settings.account_sid:
		frappe.throw(
			"Twilio Settings não configurado: Account SID ausente.",
			exc=TwilioNotConfigured,
			title="Twilio não configurado",
		)
	auth_token = settings.get_password("auth_token", raise_exception=False)
	if not auth_token:
		frappe.throw(
			"Twilio Settings não configurado: Auth Token ausente.",
			exc=TwilioNotConfigured,
			title="Twilio não configurado",
		)
	return Client(settings.account_sid, auth_token)


@frappe.whitelist()
def ping() -> dict:
	client = get_client()
	settings = get_settings()
	account = client.api.accounts(settings.account_sid).fetch()
	return {"sid": account.sid, "status": account.status, "friendly_name": account.friendly_name}
