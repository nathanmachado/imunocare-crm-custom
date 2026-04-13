"""
Webhook receptor de mensagens da Evolution API.
URL: /api/method/imunocare_crm_custom.api.whatsapp.webhook

Configurar na Evolution API:
  POST https://<seu-vps>/api/method/imunocare_crm_custom.api.whatsapp.webhook
"""

from __future__ import annotations

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def webhook() -> dict:
    """Recebe eventos da Evolution API e processa mensagens recebidas."""
    if frappe.request.method != "POST":
        frappe.throw(_("Método não permitido"), frappe.PermissionError)

    payload = frappe.request.get_json(silent=True) or {}
    event = payload.get("event", "")

    # Processar apenas mensagens recebidas (ignorar status, confirmações etc.)
    if event not in ("messages.upsert",):
        return {"status": "ignored", "event": event}

    data = payload.get("data", {})
    mensagem_obj = data.get("message", {})
    key = data.get("key", {})

    # Ignorar mensagens enviadas pelo próprio bot
    if key.get("fromMe"):
        return {"status": "ignored", "reason": "fromMe"}

    numero_raw = key.get("remoteJid", "").replace("@s.whatsapp.net", "").replace("@g.us", "")
    if not numero_raw:
        return {"status": "error", "reason": "no_number"}

    texto = (
        mensagem_obj.get("conversation")
        or mensagem_obj.get("extendedTextMessage", {}).get("text")
        or ""
    ).strip()

    instance = payload.get("instance", "")
    canal_name = _canal_por_instance(instance)
    if not canal_name:
        frappe.log_error(f"Canal WhatsApp não encontrado para instance: {instance}", "Webhook WhatsApp")
        return {"status": "error", "reason": "canal_not_found"}

    frappe.set_user("Administrator")
    _processar_mensagem(numero=numero_raw, texto=texto, canal_name=canal_name)
    return {"status": "ok"}


def _canal_por_instance(instance: str) -> str | None:
    resultado = frappe.get_all(
        "Canal WhatsApp",
        filters={"instance_name": instance, "ativo": 1},
        fields=["name"],
        limit=1,
    )
    return resultado[0].name if resultado else None


def _processar_mensagem(numero: str, texto: str, canal_name: str) -> None:
    from imunocare_crm_custom.whatsapp.client import _normalizar_numero, _registrar_mensagem
    from imunocare_crm_custom.whatsapp.bot import deve_usar_bot, responder_com_bot

    numero = _normalizar_numero(numero)
    lead_name = _get_ou_criar_lead(numero=numero, canal_name=canal_name)

    _registrar_mensagem(
        canal_name=canal_name,
        numero=numero,
        mensagem=texto,
        direcao="Entrada",
        lead_name=lead_name,
    )

    if texto and deve_usar_bot():
        responder_com_bot(
            lead_name=lead_name,
            numero=numero,
            canal_name=canal_name,
            mensagem=texto,
        )


def _get_ou_criar_lead(numero: str, canal_name: str) -> str:
    """Busca Lead existente pelo número WhatsApp ou cria um novo."""
    existente = frappe.get_all(
        "CRM Lead",
        filters={"whatsapp_numero": numero},
        fields=["name"],
        limit=1,
    )
    if existente:
        return existente[0].name

    lead = frappe.get_doc(
        {
            "doctype": "CRM Lead",
            "first_name": numero,
            "mobile_no": numero,
            "whatsapp_numero": numero,
            "canal_whatsapp": canal_name,
            "canal_origem": "WhatsApp",
            "source": "WhatsApp",
        }
    )
    lead.insert(ignore_permissions=True)
    frappe.db.commit()
    return lead.name
