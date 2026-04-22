from __future__ import annotations

import re

BR_COUNTRY_CODE = "55"


def strip_non_digits(s: str) -> str:
	return re.sub(r"\D+", "", s or "")


def normalize_phone(raw: str) -> str:
	"""Normaliza telefone para E.164 assumindo Brasil quando DDI ausente.

	Aceita: '+5511999999999', '5511999999999', '11999999999', '(11) 99999-9999',
	        'whatsapp:+5511999999999'.
	Retorna: '+5511999999999' ou '' se inválido.
	"""
	if not raw:
		return ""
	raw = raw.strip()
	if raw.startswith("whatsapp:"):
		raw = raw[len("whatsapp:") :].strip()

	has_plus = raw.startswith("+")
	digits = strip_non_digits(raw)

	if not digits:
		return ""

	# Com + explícito: respeita DDI informado (não aplica default BR)
	if has_plus:
		if 8 <= len(digits) <= 15:
			return "+" + digits
		return ""

	# Sem +: se começa com 55 e tem 12/13 dígitos, assume E.164 BR
	if digits.startswith(BR_COUNTRY_CODE) and len(digits) in (12, 13):
		return "+" + digits

	# Sem +: DDD + número (10 ou 11 dígitos) → aplica default BR
	if len(digits) in (10, 11):
		return "+" + BR_COUNTRY_CODE + digits

	return ""


def is_valid_br_phone(raw: str) -> bool:
	return bool(normalize_phone(raw))


def to_whatsapp_addr(e164: str) -> str:
	if not e164:
		return ""
	if e164.startswith("whatsapp:"):
		return e164
	return f"whatsapp:{e164}"
