from __future__ import annotations

import json
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from imunocare_crm_custom.api import survey as survey_api
from imunocare_crm_custom.utils import token as token_mod

PHONE_TEST = "+5511922220001"
AGENT_EMAIL = "survey-agent@example.com"
TEST_SECRET = "imunocare-test-secret-0123456789ab"


def _cleanup() -> None:
	for qf in frappe.get_all(
		"Quality Feedback", filters={"crm_lead": ("like", "%")}, pluck="name"
	):
		frappe.delete_doc("Quality Feedback", qf, ignore_permissions=True, force=True)
	for lead in frappe.get_all(
		"CRM Lead", filters={"first_name": ("like", "Survey Test%")}, pluck="name"
	):
		for t in frappe.get_all(
			"ToDo", filters={"reference_type": "CRM Lead", "reference_name": lead}, pluck="name"
		):
			frappe.delete_doc("ToDo", t, ignore_permissions=True, force=True)
		for c in frappe.get_all(
			"Communication",
			filters={"reference_doctype": "CRM Lead", "reference_name": lead},
			pluck="name",
		):
			frappe.delete_doc("Communication", c, ignore_permissions=True, force=True)
		for cl in frappe.get_all(
			"CRM Call Log",
			filters={"reference_doctype": "CRM Lead", "reference_docname": lead},
			pluck="name",
		):
			frappe.delete_doc("CRM Call Log", cl, ignore_permissions=True, force=True)
		frappe.delete_doc("CRM Lead", lead, ignore_permissions=True, force=True)
	frappe.db.commit()


def _with_secret():
	frappe.local.conf["imunocare_survey_secret"] = TEST_SECRET


class TestSurveyToken(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._orig_secret = frappe.local.conf.get("imunocare_survey_secret")
		_with_secret()

	@classmethod
	def tearDownClass(cls):
		if cls._orig_secret is None:
			frappe.local.conf.pop("imunocare_survey_secret", None)
		else:
			frappe.local.conf["imunocare_survey_secret"] = cls._orig_secret
		super().tearDownClass()

	def test_roundtrip_token_returns_same_lead(self):
		t = token_mod.generate_survey_token("CRM-LEAD-TEST-01")
		self.assertEqual(token_mod.verify_survey_token(t), "CRM-LEAD-TEST-01")

	def test_tampered_signature_raises(self):
		t = token_mod.generate_survey_token("CRM-LEAD-TEST-02")
		bad = t[:-4] + "AAAA"
		with self.assertRaises(token_mod.SurveyTokenError):
			token_mod.verify_survey_token(bad)

	def test_expired_token_raises(self):
		with patch.object(token_mod.time, "time", return_value=time.time() - 10 * 86400):
			t = token_mod.generate_survey_token("CRM-LEAD-TEST-03", expiry_days=7)
		with self.assertRaises(token_mod.SurveyTokenError):
			token_mod.verify_survey_token(t)

	def test_malformed_token_raises(self):
		with self.assertRaises(token_mod.SurveyTokenError):
			token_mod.verify_survey_token("not.a.valid.token")
		with self.assertRaises(token_mod.SurveyTokenError):
			token_mod.verify_survey_token("xxxx")

	def test_wrong_secret_rejects_foreign_token(self):
		t = token_mod.generate_survey_token("CRM-LEAD-TEST-04")
		frappe.local.conf["imunocare_survey_secret"] = "different-secret-00000000000000"
		try:
			with self.assertRaises(token_mod.SurveyTokenError):
				token_mod.verify_survey_token(t)
		finally:
			_with_secret()


class TestSurveyClose(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._orig_secret = frappe.local.conf.get("imunocare_survey_secret")
		_with_secret()
		_cleanup()
		if not frappe.db.exists("User", AGENT_EMAIL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": AGENT_EMAIL,
					"first_name": "Survey",
					"last_name": "Agent",
					"send_welcome_email": 0,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		if frappe.db.exists("User", AGENT_EMAIL):
			frappe.delete_doc("User", AGENT_EMAIL, ignore_permissions=True, force=True)
		if cls._orig_secret is None:
			frappe.local.conf.pop("imunocare_survey_secret", None)
		else:
			frappe.local.conf["imunocare_survey_secret"] = cls._orig_secret
		super().tearDownClass()

	def setUp(self):
		_cleanup()
		frappe.set_user(AGENT_EMAIL)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _mk_lead(self, suffix: str) -> str:
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": f"Survey Test {suffix}",
				"mobile_no": PHONE_TEST,
				"source_channel": "WhatsApp",
			}
		).insert(ignore_permissions=True)
		return lead.name

	def _seed_interaction(self, lead: str) -> None:
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "WhatsApp",
				"sent_or_received": "Received",
				"content": "oi",
				"status": "Open",
				"twilio_message_sid": f"SMsurvey{int(time.time()*1000) % 10**18:018d}",
				"whatsapp_direction": "inbound",
				"whatsapp_status": "received",
				"whatsapp_from": f"whatsapp:{PHONE_TEST}",
				"reference_doctype": "CRM Lead",
				"reference_name": lead,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_close_without_interaction_raises(self):
		lead = self._mk_lead("nointer")
		with self.assertRaises(survey_api.LeadNotInteracted):
			survey_api.close_lead(lead=lead, send_invite=False)

	def test_close_records_atendente_and_timestamp(self):
		lead = self._mk_lead("close")
		self._seed_interaction(lead)

		result = survey_api.close_lead(lead=lead, send_invite=False)
		self.assertEqual(result["status"], "closed")
		self.assertEqual(result["atendente_encerramento"], AGENT_EMAIL)
		self.assertTrue(result["token"])

		doc = frappe.get_doc("CRM Lead", lead)
		self.assertEqual(doc.atendente_encerramento, AGENT_EMAIL)
		self.assertEqual(doc.avaliacao_enviada, 1)
		self.assertIsNotNone(doc.encerramento_datetime)

	def test_close_is_idempotent(self):
		lead = self._mk_lead("idem")
		self._seed_interaction(lead)
		first = survey_api.close_lead(lead=lead, send_invite=False)
		second = survey_api.close_lead(lead=lead, send_invite=False)
		self.assertEqual(first["status"], "closed")
		self.assertEqual(second["status"], "already_closed")
		self.assertEqual(
			first["atendente_encerramento"], second["atendente_encerramento"]
		)


class TestSurveySubmit(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._orig_secret = frappe.local.conf.get("imunocare_survey_secret")
		_with_secret()
		_cleanup()
		if not frappe.db.exists("User", AGENT_EMAIL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": AGENT_EMAIL,
					"first_name": "Survey",
					"last_name": "Agent",
					"send_welcome_email": 0,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		if frappe.db.exists("User", AGENT_EMAIL):
			frappe.delete_doc("User", AGENT_EMAIL, ignore_permissions=True, force=True)
		if cls._orig_secret is None:
			frappe.local.conf.pop("imunocare_survey_secret", None)
		else:
			frappe.local.conf["imunocare_survey_secret"] = cls._orig_secret
		super().tearDownClass()

	def setUp(self):
		_cleanup()

	def _closed_lead(self, suffix: str) -> tuple[str, str]:
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": f"Survey Test {suffix}",
				"mobile_no": PHONE_TEST,
				"source_channel": "WhatsApp",
				"atendente_encerramento": AGENT_EMAIL,
				"avaliacao_enviada": 1,
			}
		).insert(ignore_permissions=True)
		token = token_mod.generate_survey_token(lead.name)
		return lead.name, token

	def test_submit_creates_quality_feedback_with_comment(self):
		lead, token = self._closed_lead("submit")
		ratings = {"Canal": 5, "Cordialidade": 4, "Resolução": 5, "Tempo de resposta": 4}
		result = survey_api.submit_feedback(
			token=token,
			ratings=json.dumps(ratings),
			comment="Equipe muito atenciosa, parabéns!",
		)
		self.assertTrue(result.get("ok"))
		qf = frappe.get_doc("Quality Feedback", result["feedback"])
		self.assertEqual(qf.crm_lead, lead)
		self.assertEqual(qf.document_type, "User")
		self.assertEqual(qf.document_name, AGENT_EMAIL)
		self.assertIn("atenciosa", qf.comment)
		self.assertEqual(len(qf.parameters), 4)

	def test_submit_invalid_token_returns_400(self):
		result = survey_api.submit_feedback(token="broken.token.here.xxx", ratings={})
		self.assertEqual(frappe.local.response.get("http_status_code"), 400)
		self.assertIn("error", result)

	def test_submit_duplicate_returns_409(self):
		lead, token = self._closed_lead("dup")
		ratings = {"Canal": 5, "Cordialidade": 5, "Resolução": 5, "Tempo de resposta": 5}
		survey_api.submit_feedback(token=token, ratings=ratings, comment="")
		frappe.local.response = frappe._dict()
		result = survey_api.submit_feedback(token=token, ratings=ratings, comment="")
		self.assertEqual(frappe.local.response.get("http_status_code"), 409)
		self.assertEqual(result.get("error"), "already_submitted")

	def test_submit_without_valid_ratings_returns_400(self):
		lead, token = self._closed_lead("norating")
		result = survey_api.submit_feedback(token=token, ratings={"Canal": 99}, comment="x")
		self.assertEqual(frappe.local.response.get("http_status_code"), 400)
		self.assertEqual(result.get("error"), "no_valid_ratings")

	def test_submit_without_comment_is_allowed(self):
		lead, token = self._closed_lead("nocomment")
		result = survey_api.submit_feedback(
			token=token,
			ratings={"Canal": 5, "Cordialidade": 5, "Resolução": 5, "Tempo de resposta": 5},
			comment="",
		)
		self.assertTrue(result.get("ok"))
		qf = frappe.get_doc("Quality Feedback", result["feedback"])
		self.assertEqual(qf.comment or "", "")

	def test_landing_page_radios_have_distinct_groups_per_parameter(self):
		"""Regressão: cada parâmetro deve ter seu próprio name de grupo de radio.

		Bug original: o template usava `name="rating_{{ loop.index0 }}"` mas
		`loop` apontava para o loop interno (1..5), repetindo os mesmos 5 nomes
		em todos os parâmetros — clicar em um parâmetro deselecionava o mesmo
		valor em outro parâmetro, e o submit acabava enviando ratings vazio,
		retornando 400 no_valid_ratings.

		Renderiza o trecho relevante do template via Jinja diretamente
		(sem o `extends "templates/web.html"` que exige contexto web HTTP).
		"""
		import re
		from jinja2 import Environment

		# Snippet mínimo replicando o trecho de geração de radios do template
		snippet = """
		{% for param in parameters %}
		{% set param_idx = loop.index0 %}
		{% for n in range(1, 6) %}
			<input type="radio" name="rating_param_{{ param_idx }}" data-param="{{ param }}" value="{{ n }}" required>
		{% endfor %}
		{% endfor %}
		"""
		params = ["Canal", "Cordialidade", "Resolução", "Tempo de resposta"]
		html = Environment().from_string(snippet).render(parameters=params)
		names = set(re.findall(r'name="([^"]+)"', html))
		self.assertEqual(
			len(names), len(params),
			msg=f"esperava {len(params)} grupos distintos, obteve {len(names)}: {names}",
		)
		# Sanity: o template real não pode ter regredido para `name="rating_{{ loop.index0 }}"`
		import os
		template_path = os.path.join(
			os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
			"www", "avaliacao.html",
		)
		with open(template_path, encoding="utf-8") as f:
			tpl = f.read()
		self.assertNotIn(
			'name="rating_{{ loop.index0 }}"', tpl,
			msg="template regrediu para o pattern bugado de loop interno",
		)
		self.assertIn(
			"set param_idx = loop.index0", tpl,
			msg="template não está aliasando o loop externo de parâmetros",
		)
		# Regressão CSRF: fetch deve ser credentials: "omit" para não usar a sessão
		# do browser quando um System Manager logado abrir a página de avaliação.
		# Sem isso, Frappe exige CSRF token válido e devolve 400 BAD REQUEST.
		self.assertIn(
			'credentials: "omit"', tpl,
			msg="fetch do submit precisa de credentials: 'omit' (request guest puro)",
		)
