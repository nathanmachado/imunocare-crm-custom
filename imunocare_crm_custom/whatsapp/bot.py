"""
Bot IA de atendimento via Claude API.
Usado fora do horário comercial ou quando nenhum atendente responde em 5 min.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_datetime, now_datetime


_HORARIO_INICIO = 8   # 08:00
_HORARIO_FIM = 18     # 18:00
_DIAS_UTEIS = (0, 1, 2, 3, 4)  # seg–sex (weekday 0=seg)


def deve_usar_bot() -> bool:
    """Retorna True fora do horário comercial."""
    agora = now_datetime()
    if agora.weekday() not in _DIAS_UTEIS:
        return True
    return not (_HORARIO_INICIO <= agora.hour < _HORARIO_FIM)


def responder_com_bot(lead_name: str, numero: str, canal_name: str, mensagem: str) -> None:
    """Gera resposta IA via Claude API e envia pelo WhatsApp."""
    from imunocare_crm_custom.whatsapp.client import enviar_mensagem

    api_key = frappe.conf.get("anthropic_api_key")
    if not api_key:
        frappe.log_error("anthropic_api_key não configurada em site_config.json", "Bot IA WhatsApp")
        return

    historico = _get_historico(lead_name, limite=10)
    resposta = _chamar_claude(api_key=api_key, mensagem=mensagem, historico=historico)
    enviar_mensagem(numero=numero, mensagem=resposta, canal_name=canal_name)


def _get_historico(lead_name: str, limite: int = 10) -> list[dict]:
    mensagens = frappe.get_all(
        "Mensagem WhatsApp",
        filters={"lead": lead_name},
        fields=["direcao", "mensagem", "creation"],
        order_by="creation asc",
        limit=limite,
    )
    historico = []
    for m in mensagens:
        role = "user" if m.direcao == "Entrada" else "assistant"
        historico.append({"role": role, "content": m.mensagem})
    return historico


def _chamar_claude(api_key: str, mensagem: str, historico: list[dict]) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = (
        "Você é um assistente virtual da Imunocare, clínica especializada em vacinas e longevidade. "
        "Responda de forma simpática, objetiva e em português brasileiro. "
        "Você pode: informar sobre vacinas disponíveis, tirar dúvidas gerais sobre imunização, "
        "informar o horário de funcionamento (segunda a sexta, 8h às 18h) e orientar sobre agendamento. "
        "Nunca forneça diagnósticos médicos. Para situações urgentes, oriente buscar atendimento presencial. "
        "Informe que um atendente humano retornará no próximo horário comercial."
    )

    messages = historico + [{"role": "user", "content": mensagem}]

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


def gerar_resumo_semanal() -> None:
    """Tarefa semanal: gera resumo IA dos atendimentos da semana."""
    from frappe.utils import add_days

    api_key = frappe.conf.get("anthropic_api_key")
    if not api_key:
        return

    data_inicio = add_days(now_datetime(), -7)
    mensagens = frappe.get_all(
        "Mensagem WhatsApp",
        filters={"creation": [">=", data_inicio]},
        fields=["mensagem", "direcao", "creation", "canal"],
        order_by="creation asc",
        limit=500,
    )
    if not mensagens:
        return

    texto = "\n".join(
        f"[{m.creation}] {'Cliente' if m.direcao == 'Entrada' else 'Atendente'}: {m.mensagem}"
        for m in mensagens
    )

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Analise os atendimentos via WhatsApp da última semana e gere um resumo executivo com:\n"
                    f"1. Volume e principais temas das conversas\n"
                    f"2. Perguntas mais frequentes\n"
                    f"3. Sugestões de melhoria no atendimento\n\n"
                    f"Dados:\n{texto[:8000]}"
                ),
            }
        ],
    )

    doc = frappe.get_doc(
        {
            "doctype": "Resumo IA Atendimento",
            "data_inicio": data_inicio,
            "data_fim": now_datetime(),
            "resumo": response.content[0].text,
            "total_mensagens": len(mensagens),
        }
    )
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
