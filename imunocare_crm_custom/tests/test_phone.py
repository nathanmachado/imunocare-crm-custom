from __future__ import annotations

import unittest

from imunocare_crm_custom.utils.phone import (
	is_valid_br_phone,
	normalize_phone,
	to_whatsapp_addr,
)


class TestNormalizePhone(unittest.TestCase):
	def test_full_e164_brazil(self):
		self.assertEqual(normalize_phone("+5511999999999"), "+5511999999999")

	def test_digits_only_with_ddi(self):
		self.assertEqual(normalize_phone("5511999999999"), "+5511999999999")

	def test_ddd_plus_mobile_11_digits(self):
		self.assertEqual(normalize_phone("11999999999"), "+5511999999999")

	def test_ddd_plus_landline_10_digits(self):
		self.assertEqual(normalize_phone("1133334444"), "+551133334444")

	def test_masked_mobile(self):
		self.assertEqual(normalize_phone("(11) 99999-9999"), "+5511999999999")

	def test_whatsapp_prefix_stripped(self):
		self.assertEqual(normalize_phone("whatsapp:+5511999999999"), "+5511999999999")

	def test_empty(self):
		self.assertEqual(normalize_phone(""), "")
		self.assertEqual(normalize_phone(None), "")

	def test_junk_returns_empty(self):
		self.assertEqual(normalize_phone("abc"), "")
		self.assertEqual(normalize_phone("123"), "")

	def test_international_preserved_when_plus(self):
		self.assertEqual(normalize_phone("+14155552671"), "+14155552671")

	def test_is_valid_br_phone(self):
		self.assertTrue(is_valid_br_phone("11999999999"))
		self.assertFalse(is_valid_br_phone("abc"))

	def test_to_whatsapp_addr(self):
		self.assertEqual(to_whatsapp_addr("+5511999999999"), "whatsapp:+5511999999999")
		self.assertEqual(to_whatsapp_addr("whatsapp:+5511999999999"), "whatsapp:+5511999999999")
		self.assertEqual(to_whatsapp_addr(""), "")

	# --- Regressão: '9' inicial de celular BR (ANATEL pós-2012) ---
	# Twilio WhatsApp Sandbox entrega WaId sem o 9 ('553491911881') e a telefonia
	# real sempre traz com 9 ('+5534991911881'). Sem normalização, o mesmo
	# contato vira Lead duplicado entre os dois canais.

	def test_br_cell_missing_9_with_plus(self):
		self.assertEqual(normalize_phone("+553491911881"), "+5534991911881")

	def test_br_cell_missing_9_digits_only(self):
		self.assertEqual(normalize_phone("553491911881"), "+5534991911881")

	def test_br_cell_missing_9_whatsapp_prefix(self):
		self.assertEqual(normalize_phone("whatsapp:+553491911881"), "+5534991911881")

	def test_br_cell_missing_9_local_10_digits(self):
		# 10 dígitos com primeiro dígito do número 8 → celular legado missing 9
		self.assertEqual(normalize_phone("3488887777"), "+5534988887777")

	def test_br_cell_with_9_unchanged(self):
		# 13 dígitos já normalizado: não duplica o 9
		self.assertEqual(normalize_phone("+5534991911881"), "+5534991911881")
		self.assertEqual(normalize_phone("5534991911881"), "+5534991911881")

	def test_br_landline_keeps_8_digits(self):
		# Fixo (primeiro dígito 2-5) NÃO recebe 9
		self.assertEqual(normalize_phone("+551133334444"), "+551133334444")
		self.assertEqual(normalize_phone("1133334444"), "+551133334444")
		self.assertEqual(normalize_phone("+551122223333"), "+551122223333")

	def test_international_non_br_not_touched(self):
		# Outros DDIs não devem receber injeção do 9
		self.assertEqual(normalize_phone("+13853233431"), "+13853233431")
		self.assertEqual(normalize_phone("+447911123456"), "+447911123456")
