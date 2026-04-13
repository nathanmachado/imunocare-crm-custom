"""
Cliente Evolution API para envio de mensagens WhatsApp.
Credenciais lidas do Canal WhatsApp configurado no banco — nunca em código.
"""

import frappe
import requests


def _get_canal(canal_name: str) -> dict:
    return frappe.get_cached_doc("Canal WhatsApp", canal_name).as_dict()


def enviar_mensagem(numero: str, mensagem: str, canal_name: str) -> dict:
    """Envia mensagem de texto via Evolution API."""
    canal = _get_canal(canal_name)
    numero = _normalizar_numero(numero)

    url = f"{canal.api_url.rstrip('/')}/message/sendText/{canal.instance_name}"
    headers = {"apikey": canal.get_password("api_key"), "Content-Type": "application/json"}
    payload = {"number": numero, "text": mensagem}

    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()

    _registrar_mensagem(canal_name=canal_name, numero=numero, mensagem=mensagem, direcao="Saída")
    return resp.json()


def _normalizar_numero(numero: str) -> str:
    """Garante DDI 55 (Brasil) e remove caracteres não numéricos."""
    digitos = "".join(c for c in numero if c.isdigit())
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    return digitos


def _registrar_mensagem(
    canal_name: str,
    numero: str,
    mensagem: str,
    direcao: str,
    lead_name: str | None = None,
) -> None:
    doc = frappe.get_doc(
        {
            "doctype": "Mensagem WhatsApp",
            "canal": canal_name,
            "numero": numero,
            "mensagem": mensagem,
            "direcao": direcao,
            "lead": lead_name,
        }
    )
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
