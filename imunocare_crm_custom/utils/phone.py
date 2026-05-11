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

	Para números BR de celular, garante o '9' inicial obrigatório (regra ANATEL
	pós-2012). Necessário para unificar canais: Twilio WhatsApp Sandbox entrega
	o WaId sem o '9' e a telefonia real sempre traz com '9', causando duplicatas
	se não normalizado para o mesmo formato.
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
		if not (8 <= len(digits) <= 15):
			return ""
		if digits.startswith(BR_COUNTRY_CODE):
			digits = _bridge_br_cell(digits)
		return "+" + digits

	# Sem +: se começa com 55 e tem 12/13 dígitos, assume E.164 BR
	if digits.startswith(BR_COUNTRY_CODE) and len(digits) in (12, 13):
		digits = _bridge_br_cell(digits)
		return "+" + digits

	# Sem +: DDD + número (10 ou 11 dígitos) → aplica default BR
	if len(digits) in (10, 11):
		digits = BR_COUNTRY_CODE + digits
		digits = _bridge_br_cell(digits)
		return "+" + digits

	return ""


def _bridge_br_cell(digits: str) -> str:
	"""Adiciona o '9' inicial obrigatório de celular BR se faltando.

	Aplica apenas a números BR com exatamente 12 dígitos (55 + DDD + 8 dígitos),
	quando o primeiro dígito do número local for 6/7/8/9 (celular legado).
	Fixos começam com 2/3/4/5 e ficam intactos.
	"""
	if not digits.startswith(BR_COUNTRY_CODE) or len(digits) != 12:
		return digits
	first_local_digit = digits[4]  # após '55' (2) + DDD (2)
	if first_local_digit in "6789":
		return digits[:4] + "9" + digits[4:]
	return digits


def is_valid_br_phone(raw: str) -> bool:
	return bool(normalize_phone(raw))


def to_whatsapp_addr(e164: str) -> str:
	if not e164:
		return ""
	if e164.startswith("whatsapp:"):
		return e164
	return f"whatsapp:{e164}"
