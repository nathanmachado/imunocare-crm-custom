from __future__ import annotations

import frappe
from frappe.model.document import Document


class MessageTemplate(Document):
	def validate(self):
		if self.twilio_content_sid and not self.twilio_content_sid.startswith("HX"):
			frappe.throw("Twilio Content SID deve começar com 'HX'.")
