import frappe
from frappe.model.document import Document


class TwilioSettings(Document):
	def validate(self):
		if self.whatsapp_sender and not self.whatsapp_sender.startswith("whatsapp:"):
			frappe.throw(
				"WhatsApp Sender deve começar com 'whatsapp:' seguido do número em E.164 (ex: whatsapp:+5511999999999)"
			)
		if self.voice_number and not self.voice_number.startswith("+"):
			frappe.throw("Voice Number deve estar em formato E.164 iniciando com '+' (ex: +5511999999999)")
		if self.recording_retention_days is not None and self.recording_retention_days < 1:
			frappe.throw("Retenção de gravações deve ser ao menos 1 dia")
