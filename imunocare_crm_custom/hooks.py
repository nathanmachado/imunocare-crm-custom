app_name = "imunocare_crm_custom"
app_title = "Imunocare CRM Custom"
app_publisher = "Imunocare"
app_description = "Personalização do Frappe CRM: WhatsApp Business e integração Healthcare"
app_email = "tech@imunocare.com.br"
app_license = "mit"

required_apps = ["crm"]

# Fixtures exportados pelo app (Custom Fields no CRM Lead)
fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "Imunocare CRM Custom"]]},
]

# Hooks em DocTypes do Frappe CRM
doc_events = {
    "CRM Lead": {
        "after_insert": "imunocare_crm_custom.whatsapp.events.lead_after_insert",
    },
}

# Tarefas agendadas
scheduler_events = {
    "weekly": [
        "imunocare_crm_custom.whatsapp.bot.gerar_resumo_semanal",
    ],
}
