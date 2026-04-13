from frappe.model.document import Document
from frappe.utils import now_datetime


class AvaliacaoAtendimento(Document):
    def before_insert(self):
        if not self.data_avaliacao:
            self.data_avaliacao = now_datetime()
