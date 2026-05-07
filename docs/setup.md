# Guia de Configuração — Imunocare CRM Custom

Este documento descreve **tudo** o que precisa ser configurado para colocar em
operação as features do app `imunocare_crm_custom`:

- **WhatsApp Business** via Twilio (envio e recebimento, templates HSM)
- **Voz (click-to-call + IVR de consentimento + gravação)** via Twilio
- **Survey pós-atendimento** com token assinado (HMAC-SHA256)
- **Botões no CRM Portal** (`/crm/leads/...`) via CRM Form Script
- **Schedulers** de retenção (LGPD), retry de convite e tag de inatividade

A ordem abaixo é de cima para baixo: siga na sequência em um ambiente novo.

---

## 0. Onde guardamos este conhecimento

Este arquivo vive em `apps/imunocare_crm_custom/docs/setup.md` — versiona
junto com o código, migra automaticamente com o repo, e pode ser renderizado
pelo GitHub/Gitea.

**Sugestão para agrupar conhecimento do projeto**: manter tudo em
`apps/imunocare_crm_custom/docs/` (nest abaixo de `docs/` quando crescer),
dividido por tema:

```
apps/imunocare_crm_custom/docs/
├── setup.md              ← este arquivo
├── architecture.md       ← decisões de arquitetura, diagramas
├── operations.md         ← runbooks (reiniciar worker, purgar fila, …)
├── testing.md             ← como rodar testes, criar lead de teste
└── adr/                   ← Architecture Decision Records
    └── 0001-token-hmac.md
```

Alternativa válida: repositório separado `imunocare-wiki` com o mesmo layout —
se a equipe não-dev (atendentes/gestores) precisar consultar com frequência.
Recomendação: ficar em `docs/` dentro do app enquanto o time é pequeno; migrar
quando a documentação passar a ser consumida por pessoas que não mexem no
código.

---

## 1. Pré-requisitos

| Item | Versão / Detalhe |
|---|---|
| Frappe Framework | v15 |
| Frappe CRM | última versão v15 |
| ERPNext (Healthcare) | v15 (para o doctype `Patient`) |
| Python | 3.10+ |
| `twilio` (Python SDK) | 8.5+ (já em `pyproject.toml`) |
| Conta Twilio | paga (Sandbox só serve para POC) |
| Meta Business Manager | verificado |
| WhatsApp Business Account (WABA) | registrado e ligado ao Twilio |
| Domínio público com HTTPS | obrigatório — Twilio não envia callback para IP cru |

---

## 2. `site_config.json` — segredos locais

Caminho: `frappe-bench/sites/<site>/site_config.json`

Adicione:

```json
{
  "imunocare_survey_secret": "<64 bytes random, hex ou base64>"
}
```

**Para que serve**: assinatura HMAC-SHA256 dos tokens de pesquisa enviados ao
cliente (`/avaliacao?token=...`). Se ausente, cai em `encryption_key` (já
presente em toda instalação Frappe) — mas **recomenda-se gerar uma chave
dedicada**, rotacionável sem invalidar credenciais de outras features.

Gerar:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Rotação**: trocar o valor invalida todos os tokens em circulação. Rode o
scheduler `retry_survey_invites` logo em seguida para redisparar os convites
pendentes (ele regera o token para cada lead que ainda não respondeu).

---

## 3. `common_site_config.json` — referências úteis

Nada obrigatório aqui para este app. Boas práticas já definidas:

- `developer_mode: 1` em dev (já está)
- `maintenance_mode`: use quando rodar `bench migrate` em produção

---

## 4. Instalação do app

```bash
cd frappe-bench
bench get-app imunocare_crm_custom <URL_REPO> --branch main
bench --site <site> install-app imunocare_crm_custom
bench --site <site> migrate
bench restart
```

O `install-app` + `migrate` executam `install_custom_fields()`
(`custom_fields.py`), que:

1. Cria Custom Fields em: `CRM Lead`, `Communication`, `CRM Call Log`, `Quality Feedback`
2. Altera o Property Setter de `Communication.communication_medium` para incluir `WhatsApp`
3. Insere o status `Missed Call` em `CRM Lead Status`
4. Cria o Role `Imunocare Atendente`
5. Cria o Assignment Rule `Imunocare CRM Lead Round Robin` (começa desabilitado — ativa sozinho quando houver users com o role)
6. Cria o Quality Feedback Template `Avaliação de Atendimento Imunocare`
7. Instala/atualiza o CRM Form Script `Imunocare CRM Lead Actions` (3 botões no Portal)

Confirme:

```bash
bench --site <site> console
>>> frappe.db.exists("CRM Form Script", "Imunocare CRM Lead Actions")
>>> frappe.db.exists("Quality Feedback Template", "Avaliação de Atendimento Imunocare")
>>> frappe.db.exists("Role", "Imunocare Atendente")
```

---

## 5. Configuração da conta Twilio — passo a passo

### 5.1 Criar a conta

1. `https://www.twilio.com/try-twilio` — conta paga (Sandbox não suporta
   Content Templates aprovados, Status Callback com signature nem números BR).
2. Upgrade de Trial → Pay-as-you-go (exige cartão).
3. Ativar **Messaging Services** e **Voice** no Console.

### 5.2 Registrar o número de voz (PSTN)

Console → **Phone Numbers → Buy a Number**

- País: Brasil
- Capabilities: **Voice** obrigatório, SMS opcional
- Guarde o número em E.164, ex.: `+5511999999999`

Após a compra, abra o número → aba **Voice Configuration**:

| Campo | Valor |
|---|---|
| A CALL COMES IN | `Webhook` → `https://<domain>/api/method/imunocare_crm_custom.api.twilio.webhook` → `HTTP POST` |
| PRIMARY HANDLER FAILS | (deixe vazio para subir alerta) |
| CALL STATUS CHANGES | `https://<domain>/api/method/imunocare_crm_custom.api.twilio.voice_status` → `HTTP POST` |

### 5.3 Registrar o número WhatsApp (via Meta → Twilio Sender)

> **Atenção**: WhatsApp Business exige **Meta Business Manager verificado**.
> Veja a seção 6 antes de continuar.

Console → **Messaging → Senders → WhatsApp senders → Add a WhatsApp Sender**

1. Selecione o número (pode ser o mesmo de voz se suportar, ou um dedicado).
2. Twilio dispara um OTP para o Meta BM → aprovar o vínculo.
3. Aguardar status **Approved** (normalmente 1–3h).
4. Guarde o número em E.164 com prefixo, ex.: `whatsapp:+5511999999999`.

Após aprovação, abra o sender → aba **Configure** → **Messaging Webhooks**:

| Campo | Valor |
|---|---|
| WHEN A MESSAGE COMES IN | `https://<domain>/api/method/imunocare_crm_custom.api.twilio.webhook` → `HTTP POST` |
| STATUS CALLBACK URL | `https://<domain>/api/method/imunocare_crm_custom.api.twilio.message_status` → `HTTP POST` |

### 5.4 Criar Content Templates (HSM) aprovados

Console → **Content Template Builder → Create new content**

Para cada template (Imunocare já usa pelo menos um de **utility** e um de
**marketing**):

1. **Name**: padrão `imunocare_<slug>` (ex.: `imunocare_avaliacao_invite`)
2. **Language**: `pt_BR`
3. **Category**: `UTILITY` (transactional) ou `MARKETING`
4. **Body**: use `{{1}}`, `{{2}}`… para variáveis posicionais
   ```
   Olá {{1}}, agradecemos o atendimento. Avalie em: {{2}}
   ```
5. Enviar para aprovação (**Submit for WhatsApp approval**)
6. Aguardar **Approved** (1 dia útil típico, até 5 em casos de revisão)
7. Copiar o **Content SID** (começa com `HX...`)

No Frappe, abra **Message Template** (DocType do app) e crie um registro por
template aprovado:

| Campo | Valor |
|---|---|
| Template Name | `imunocare_avaliacao_invite` |
| Channel | `WhatsApp` |
| Language | `pt_BR` |
| Category | `UTILITY` |
| Twilio Content SID | `HXxxxxxxxx...` |
| Approval Status | `Approved` (o scheduler `sync_message_templates_approval` atualiza diariamente) |
| Body | espelho do body aprovado (referência humana) |
| Variables (tabela) | uma linha por `{{n}}`, com descrição |

### 5.5 Habilitar gravação de voz (opcional, LGPD-sensitive)

Twilio grava a chamada quando o TwiML `<Dial record="record-from-answer">` é
emitido. O app já emite isso quando **ambas** condições são verdadeiras:

- `Twilio Settings.record_calls = 1`
- O cliente pressionou `1` no IVR de consentimento (DTMF) na
  `api.twilio.voice_consent`

Nenhuma config adicional no Twilio Console é necessária.

### 5.6 Signature validation (segurança obrigatória)

Todos os webhooks do app validam `X-Twilio-Signature` contra o `auth_token` em
`Twilio Settings`. Para isso funcionar:

- O `webhook_base_url` em `Twilio Settings` **deve bater exatamente** com o
  host público que o Twilio usa (inclui esquema `https://` e porta se houver).
- Não use redirects 301/302 entre Twilio → Frappe; Twilio assina a URL
  original.

---

## 6. Configuração Meta Business (WhatsApp Business Platform)

### 6.1 O que a Meta exige antes da Twilio

Twilio é **revendedor** (BSP — Business Service Provider) da API oficial da
Meta. Estes passos são feitos no **Meta Business Manager**
(`business.facebook.com`), **antes** de criar o sender WhatsApp na Twilio:

1. **Criar/escolher uma Meta Business Account** e concluir a verificação:
   - Dados cadastrais da empresa
   - Comprovante (CNPJ + endereço)
   - Verificação via documento oficial ou vídeo-call da Meta (24–72h)
2. **Registrar o domínio** usado para o Display Name
3. **Facebook Page** vinculada à Business Account (não precisa ter postagens)
4. **WhatsApp Business Account (WABA)**
   - Business Settings → Accounts → WhatsApp Accounts → Add
   - Escolher **Request access for a BSP** → buscar Twilio
5. **Phone Number Display Name**:
   - Nome comercial (ex.: "Imunocare Atendimento") precisa de aprovação
   - Sem termos promocionais, sem emoji, sem nome pessoal

Após tudo aprovado, volte para Twilio Console (seção 5.3) e finalize o
Sender.

### 6.2 Configuração em runtime na Meta

Após o sender estar em produção, a Meta controla:

- **Templates HSM** — aprovação via Twilio Content Builder roteia para a Meta;
  status pode ser visto em **Business Settings → WhatsApp Accounts → Message
  Templates**. O scheduler diário `sync_message_templates_approval` pega o
  novo status na Twilio e propaga para o doc `Message Template`.
- **Quality Rating** do número — monitore em **WhatsApp Manager →
  Performance**. Se cair para **Medium/Low**, pausamos campanhas marketing e
  mantemos apenas Utility.
- **Messaging limits** — tier inicial 250 conversas/dia → sobe
  automaticamente. A config do tier é da Meta, não tem handle no app.

### 6.3 O que **não** precisa ser configurado na Meta

- Webhooks: roteados pela Twilio. Não configure webhook direto na Meta.
- Access Token: o Twilio gerencia internamente; o app só usa Twilio SID/Token.

---

## 7. Twilio Settings no Frappe

Abra o Single DocType **Twilio Settings** (`/app/twilio-settings`):

| Campo | Exemplo | Observação |
|---|---|---|
| Account SID | `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` | Console → Dashboard |
| Auth Token | `…` | Password field; visível só em ediçao |
| Webhook Base URL | `https://crm.imunocare.com.br` | Sem barra final; sem `/api/...` |
| WhatsApp Sender | `whatsapp:+5511999999999` | Exatamente como a Twilio retorna |
| Voice Number | `+5511998887777` | E.164, sem prefixo `whatsapp:` |
| Gravar Chamadas | `1` | Requer consentimento IVR em runtime |
| Retenção de Gravações (dias) | `90` | `0` = desabilita o purge |

**Salve** — o controller valida que `Account SID` começa com `AC` e
`Auth Token` tem 32 caracteres.

---

## 8. Permissões e Roles

### 8.1 Atendentes Imunocare

Crie/edite cada usuário atendente em **User List** e adicione:

- Role: `Imunocare Atendente` (criado pelo installer)
- Role: `Sales User` (nativo do Frappe CRM — dá acesso ao CRM Lead)

O helper `sync_assignment_rule_users` (roda automático em `after_migrate` e
pode ser chamado manualmente via `bench execute`) popula o Assignment Rule
com os users ativos que têm o role.

### 8.2 Gestores

- Role: `Sales Manager` (ver relatórios, reatribuir leads)
- Role: `System Manager` (config de Twilio, templates)

---

## 9. Schedulers e workers

Os seguintes jobs são disparados via `hooks.scheduler_events`:

| Frequência | Job | Arquivo |
|---|---|---|
| daily | `tasks.leads.tag_inactive_leads` | tagueia leads sem contato há 48h+ |
| daily | `tasks.retention.purge_old_recordings` | apaga gravações > retenção |
| daily | `twilio_integration.tasks.sync_message_templates_approval` | sincroniza status HSM da Twilio |
| cron `*/15 * * * *` | `tasks.survey_retry.retry_survey_invites` | reenviar convite depois de 24h |

Para funcionar em produção, o **scheduler** precisa estar rodando:

```bash
bench --site <site> enable-scheduler     # apenas uma vez
bench --site <site> scheduler resume     # se estiver pausado
bench restart                             # aplica mudança
```

Monitorar:

```bash
bench --site <site> console
>>> frappe.get_all("Scheduled Job Log",
...   filters={"scheduled_job_type": ("like", "%imunocare%")},
...   order_by="creation desc", limit=10,
...   fields=["name", "status", "creation", "details"])
```

---

## 10. DNS, HTTPS e proxy reverso

O `webhook_base_url` precisa bater com o nome público com **TLS válido**.
Twilio rejeita self-signed.

Exemplo nginx (já presente no `imunocare-deploy/`):

```nginx
server {
    listen 443 ssl http2;
    server_name crm.imunocare.com.br;

    # ... ssl_certificate etc.

    location /api/method/imunocare_crm_custom.api.twilio.webhook  { proxy_pass http://frappe; }
    location /api/method/imunocare_crm_custom.api.twilio.message_status { proxy_pass http://frappe; }
    location /api/method/imunocare_crm_custom.api.twilio.voice_bridge { proxy_pass http://frappe; }
    location /api/method/imunocare_crm_custom.api.twilio.voice_status { proxy_pass http://frappe; }
    location /api/method/imunocare_crm_custom.api.twilio.voice_consent { proxy_pass http://frappe; }
}
```

Na prática, `location / { proxy_pass http://frappe; }` já cobre tudo. O nginx
do `bench setup nginx` faz isso por padrão.

**Teste de alcance**:

```bash
curl -I https://crm.imunocare.com.br/api/method/imunocare_crm_custom.api.twilio.webhook
# Esperado: HTTP/2 405 (GET não permitido — mas responde, então o caminho existe)
```

---

## 11. Resumo de URLs de webhook

Copiar/colar no Twilio Console. `<BASE>` = `webhook_base_url` do Settings.

| Evento | Método | URL |
|---|---|---|
| WhatsApp inbound | POST | `<BASE>/api/method/imunocare_crm_custom.api.twilio.webhook` |
| WhatsApp status callback | POST | `<BASE>/api/method/imunocare_crm_custom.api.twilio.message_status` |
| Voice inbound | POST | `<BASE>/api/method/imunocare_crm_custom.api.twilio.webhook` |
| Voice bridge (outbound) | POST | `<BASE>/api/method/imunocare_crm_custom.api.twilio.voice_bridge` |
| Voice status callback | POST | `<BASE>/api/method/imunocare_crm_custom.api.twilio.voice_status` |
| Voice consent IVR | POST | `<BASE>/api/method/imunocare_crm_custom.api.twilio.voice_consent` |
| Survey landing page | GET  | `<BASE>/avaliacao?token=...` |
| Survey submit | POST | `<BASE>/api/method/imunocare_crm_custom.api.survey.submit_feedback` |

---

## 12. Smoke test end-to-end

Após tudo configurado:

1. **Voz inbound** — ligue do celular para o `Voice Number`. Deve cair na
   saudação, oferecer consentimento de gravação (dígito 1/2), conectar com o
   atendente online (round-robin) e criar um `CRM Call Log` + `CRM Lead`.
2. **Voz outbound** — abra um lead em `/crm/leads/<id>`, clique **Ligar**
   → confirme → o celular do atendente toca; ao atender, a Twilio disca para
   o cliente.
3. **WhatsApp inbound** — mande uma mensagem para o `WhatsApp Sender` a
   partir de um celular externo. Deve criar/atualizar um lead e logar a
   `Communication` com `communication_medium=WhatsApp`.
4. **WhatsApp outbound (janela aberta)** — no Portal, **Enviar WhatsApp** →
   digita texto → envia. Cliente recebe.
5. **WhatsApp outbound (janela fechada)** — passe 24h sem interação e clique
   **Enviar WhatsApp** → lista de templates aparece → escolha → cliente
   recebe o HSM.
6. **Encerrar atendimento** — clique **Encerrar Atendimento → com convite**.
   Cliente recebe link `/avaliacao?token=...`; submete 5 estrelas; o doc
   `Quality Feedback` é criado.
7. **Retry automático** — se o cliente não abrir o convite em 24h, o
   scheduler `retry_survey_invites` dispara um segundo envio (máx 2).
8. **Purge LGPD** — após `recording_retention_days` dias, a gravação é
   removida do Twilio pelo scheduler `purge_old_recordings`.

---

## 13. Checklist de produção

- [ ] `site_config.json` com `imunocare_survey_secret`
- [ ] `Twilio Settings` preenchido e salvo
- [ ] Webhooks configurados em **todos** os números Twilio
- [ ] Signature validation testada (tente um POST com assinatura errada → 403)
- [ ] Pelo menos 1 Message Template aprovado e com Content SID preenchido
- [ ] Role `Imunocare Atendente` atribuído a ≥1 user ativo
- [ ] Assignment Rule habilitado
- [ ] Scheduler rodando
- [ ] HTTPS válido no `webhook_base_url`
- [ ] Smoke test (seção 12) completo
- [ ] Backup do site_config.json em cofre seguro

---

## 14. Troubleshooting rápido

| Sintoma | Causa comum | Fix |
|---|---|---|
| Webhook retorna 403 | Signature mismatch | `webhook_base_url` diferente do que o Twilio envia (checar proxy, https/http, barra final) |
| WhatsApp outbound retorna 63016 | Template não aprovado ou fora da janela | Usar template com `Approval Status=Approved`; checar `whatsapp_window_status` |
| Voice outbound não discar | `voice_number` vazio ou sem CNAM | Preencher `Twilio Settings.voice_number`; número deve ter Voice habilitado |
| Ligação sem gravação mesmo com consentimento | `record_calls=0` ou bridge não está usando caller_id | Ativar `record_calls`; conferir `_dial_twiml` |
| Scheduler não roda | `enable-scheduler` não executado ou site pausado | `bench --site <site> enable-scheduler && bench --site <site> scheduler resume` |
| Token de survey expira antes do retry | `DEFAULT_EXPIRY_DAYS=7` mas retry acontece em 24h | OK por design; token é regerado a cada disparo |
| Botões do Portal não aparecem | CRM Form Script desabilitado | `bench --site <site> console → frappe.db.set_value("CRM Form Script", "Imunocare CRM Lead Actions", "enabled", 1)` |

---

## 15. Referências internas

- Código: `apps/imunocare_crm_custom/`
- Testes: `apps/imunocare_crm_custom/imunocare_crm_custom/tests/` (116 tests)
- Customizações: `custom_fields.py`
- Hooks: `hooks.py`
- Scheduler: `tasks/`
- Form Script: `crm_form_scripts/crm_lead_actions.js`
- Docs CRM upstream: `apps/crm/docs/form-scripts.md`
