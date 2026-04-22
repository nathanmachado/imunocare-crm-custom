frappe.ui.form.on("CRM Lead", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Enviar WhatsApp"),
			() => imunocare_open_whatsapp_dialog(frm),
			__("Imunocare"),
		);

		frm.add_custom_button(
			__("Ligar"),
			() => imunocare_start_call(frm),
			__("Imunocare"),
		);

		if (!frm.doc.avaliacao_enviada) {
			frm.add_custom_button(
				__("Encerrar Atendimento"),
				() => imunocare_close_lead(frm),
				__("Imunocare"),
			);
		}
	},
});

function imunocare_open_whatsapp_dialog(frm) {
	frappe.call({
		method: "imunocare_crm_custom.api.whatsapp.whatsapp_window_status",
		args: { lead: frm.doc.name },
		freeze: true,
		freeze_message: __("Verificando janela de 24h..."),
	}).then((r) => {
		const status = r.message || {};
		const templates = status.templates || [];
		const open = !!status.open;

		const fields = [
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: __("Modo"),
				options: open
					? ["Texto livre", "Template (HSM)"].join("\n")
					: "Template (HSM)",
				default: open ? "Texto livre" : "Template (HSM)",
				reqd: 1,
			},
			{
				fieldname: "body",
				fieldtype: "Small Text",
				label: __("Mensagem"),
				depends_on: "eval:doc.mode === 'Texto livre'",
				mandatory_depends_on: "eval:doc.mode === 'Texto livre'",
			},
			{
				fieldname: "template",
				fieldtype: "Select",
				label: __("Template aprovado"),
				options: ["", ...templates.map((t) => t.name)].join("\n"),
				depends_on: "eval:doc.mode === 'Template (HSM)'",
				mandatory_depends_on: "eval:doc.mode === 'Template (HSM)'",
			},
			{
				fieldname: "variables",
				fieldtype: "Code",
				label: __("Variáveis (JSON)"),
				options: "JSON",
				depends_on: "eval:doc.mode === 'Template (HSM)'",
				description: __('Ex.: {"1": "Maria", "2": "10h"}'),
			},
		];

		if (!open) {
			fields.unshift({
				fieldname: "window_note",
				fieldtype: "HTML",
				options:
					'<div class="alert alert-warning">' +
					__("Janela de 24h fechada. Use um Message Template aprovado.") +
					"</div>",
			});
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Enviar WhatsApp"),
			fields,
			primary_action_label: __("Enviar"),
			primary_action(values) {
				const args = { lead: frm.doc.name };
				if (values.mode === "Texto livre") {
					args.body = values.body;
				} else {
					args.template = values.template;
					if (values.variables) args.variables = values.variables;
				}

				frappe.call({
					method: "imunocare_crm_custom.api.whatsapp.send_whatsapp_from_lead",
					args,
					freeze: true,
					freeze_message: __("Enviando..."),
				}).then((resp) => {
					if (resp.message && resp.message.ok) {
						frappe.show_alert({
							message: __("WhatsApp enviado"),
							indicator: "green",
						});
						dialog.hide();
						frm.reload_doc();
					}
				});
			},
		});
		dialog.show();
	});
}

function imunocare_start_call(frm) {
	frappe.confirm(
		__("Iniciar chamada para {0}?", [frm.doc.mobile_no || frm.doc.phone || ""]),
		() => {
			frappe.call({
				method: "imunocare_crm_custom.api.twilio.voice_start",
				args: { lead: frm.doc.name },
				freeze: true,
				freeze_message: __("Conectando chamada..."),
			}).then((r) => {
				if (r.message && r.message.call_sid) {
					frappe.show_alert({
						message: __("Chamada iniciada: {0}", [r.message.call_sid]),
						indicator: "blue",
					});
				}
			});
		},
	);
}

function imunocare_close_lead(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Encerrar atendimento"),
		fields: [
			{
				fieldtype: "HTML",
				options:
					"<p>" +
					__(
						"O atendente atual será registrado como responsável pelo encerramento e um convite de avaliação será enviado.",
					) +
					"</p>",
			},
			{
				fieldname: "send_invite",
				fieldtype: "Check",
				label: __("Enviar convite de avaliação"),
				default: 1,
			},
		],
		primary_action_label: __("Encerrar"),
		primary_action(values) {
			frappe.call({
				method: "imunocare_crm_custom.api.survey.close_lead",
				args: {
					lead: frm.doc.name,
					send_invite: values.send_invite ? 1 : 0,
				},
				freeze: true,
				freeze_message: __("Encerrando..."),
			}).then((r) => {
				if (r.message && r.message.status) {
					frappe.show_alert({
						message: __("Atendimento encerrado"),
						indicator: "green",
					});
					dialog.hide();
					frm.reload_doc();
				}
			});
		},
	});
	dialog.show();
}
