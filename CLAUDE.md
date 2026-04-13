# CLAUDE.md — imunocare_crm_custom

## Propósito
Personalização do Frappe CRM (app nativo `crm`) para integração com WhatsApp Business via Evolution API,
avaliação de atendimento (NPS/CSAT) e integração com o Frappe Healthcare.

**Nunca modificar** o app `crm` (upstream). Toda customização fica neste app.

## Dependências
- `crm` (Frappe CRM — app nativo, deve estar instalado antes)
- `imunocare_core`
- Evolution API self-hosted no VPS
- Claude API (anthropic_api_key em site_config.json)

## DocTypes Próprios (módulo: Imunocare CRM Custom)
- `Canal WhatsApp` — configuração de instância Evolution API (instance_name, api_url, api_key, telefone)
- `Mensagem WhatsApp` — histórico de mensagens (entrada/saída), linked a CRM Lead
- `Avaliacao Atendimento` — NPS 1-5, linked a CRM Lead
- `Resumo IA Atendimento` — output semanal Claude API

## Custom Fields nos DocTypes do CRM (via fixtures)
- `CRM Lead.whatsapp_numero` — número do WhatsApp do lead
- `CRM Lead.canal_whatsapp` — Link para Canal WhatsApp
- `CRM Lead.canal_origem` — Select: WhatsApp, Telefone, Website, Indicação, Presencial

## Estrutura de Código
```
imunocare_crm_custom/
├── api/
│   └── whatsapp.py      ← webhook Evolution API (allow_guest=True)
├── whatsapp/
│   ├── client.py        ← enviar_mensagem() via Evolution API
│   ├── bot.py           ← bot IA Claude API, resumo semanal
│   └── events.py        ← hooks doc_events do CRM Lead
├── fixtures/
│   └── custom_field.json← Custom Fields para CRM Lead
└── imunocare_crm_custom/doctype/
    ├── canal_whatsapp/
    ├── mensagem_whatsapp/
    ├── avaliacao_atendimento/
    └── resumo_ia_atendimento/
```

## Webhook Evolution API
- **URL:** `/api/method/imunocare_crm_custom.api.whatsapp.webhook`
- **Evento recebido:** `messages.upsert`
- **Fluxo:** recebe mensagem → busca/cria CRM Lead → salva Mensagem WhatsApp → se fora do horário comercial → bot Claude

## Configuração Necessária (site_config.json)
```json
{
  "anthropic_api_key": "sk-ant-..."
}
```

## Git Flow
Branch de trabalho: `agents/<id>/<issue>-<desc>` → PR → `test` → PR → `main`
Remoto: `https://github.com/nathanmachado/imunocare-crm-custom`
