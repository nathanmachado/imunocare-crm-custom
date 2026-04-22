from __future__ import annotations

import base64
import hashlib
import hmac
import time

import frappe

SURVEY_TOKEN_VERSION = "v1"
DEFAULT_EXPIRY_DAYS = 7


class SurveyTokenError(frappe.ValidationError):
	pass


def _secret() -> bytes:
	secret = frappe.local.conf.get("imunocare_survey_secret") or frappe.local.conf.get(
		"encryption_key"
	)
	if not secret:
		frappe.throw(
			"imunocare_survey_secret (ou encryption_key) ausente em site_config.json.",
			exc=SurveyTokenError,
		)
	if isinstance(secret, str):
		secret = secret.encode("utf-8")
	return secret


def _b64url_encode(raw: bytes) -> str:
	return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
	pad = "=" * (-len(s) % 4)
	return base64.urlsafe_b64decode(s + pad)


def generate_survey_token(lead: str, expiry_days: int = DEFAULT_EXPIRY_DAYS) -> str:
	"""Retorna token assinado HMAC-SHA256: v1.<lead_b64>.<exp>.<sig_b64>."""
	if not lead:
		frappe.throw("lead obrigatório", exc=SurveyTokenError)
	exp = int(time.time()) + int(expiry_days) * 86400
	lead_b64 = _b64url_encode(lead.encode("utf-8"))
	payload = f"{SURVEY_TOKEN_VERSION}.{lead_b64}.{exp}".encode("ascii")
	sig = hmac.new(_secret(), payload, hashlib.sha256).digest()
	return f"{SURVEY_TOKEN_VERSION}.{lead_b64}.{exp}.{_b64url_encode(sig)}"


def verify_survey_token(token: str) -> str:
	"""Valida token e retorna lead_name. Levanta SurveyTokenError se inválido/expirado."""
	if not token or not isinstance(token, str):
		frappe.throw("Token ausente.", exc=SurveyTokenError)
	parts = token.split(".")
	if len(parts) != 4:
		frappe.throw("Token malformado.", exc=SurveyTokenError)
	version, lead_b64, exp_raw, sig_b64 = parts
	if version != SURVEY_TOKEN_VERSION:
		frappe.throw("Token de versão desconhecida.", exc=SurveyTokenError)

	try:
		exp = int(exp_raw)
	except ValueError:
		frappe.throw("Token malformado (exp).", exc=SurveyTokenError)

	payload = f"{version}.{lead_b64}.{exp}".encode("ascii")
	expected = hmac.new(_secret(), payload, hashlib.sha256).digest()
	try:
		actual = _b64url_decode(sig_b64)
	except Exception:
		frappe.throw("Token malformado (sig).", exc=SurveyTokenError)
	if not hmac.compare_digest(expected, actual):
		frappe.throw("Assinatura inválida.", exc=SurveyTokenError)

	if int(time.time()) > exp:
		frappe.throw("Token expirado.", exc=SurveyTokenError)

	try:
		return _b64url_decode(lead_b64).decode("utf-8")
	except Exception:
		frappe.throw("Token malformado (lead).", exc=SurveyTokenError)
