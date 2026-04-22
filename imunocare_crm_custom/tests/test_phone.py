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
