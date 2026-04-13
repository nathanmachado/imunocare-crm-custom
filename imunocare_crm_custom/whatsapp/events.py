"""Hooks de eventos em DocTypes do Frappe CRM."""

import frappe


def lead_after_insert(doc, method=None):
    """Após criar Lead via WhatsApp, envia mensagem de boas-vindas se canal configurado."""
    if not doc.get("canal_whatsapp") or not doc.get("whatsapp_numero"):
        return

    from imunocare_crm_custom.whatsapp.client import enviar_mensagem

    nome = doc.first_name or "cliente"
    mensagem = (
        f"Olá, {nome}! 👋 Bem-vindo à Imunocare.\n"
        "Em breve um de nossos atendentes entrará em contato. "
        "Enquanto isso, fique à vontade para nos contar como podemos ajudar."
    )
    try:
        enviar_mensagem(
            numero=doc.whatsapp_numero,
            mensagem=mensagem,
            canal_name=doc.canal_whatsapp,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Erro ao enviar boas-vindas WhatsApp")
