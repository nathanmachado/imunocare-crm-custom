class CRMLead {
	onLoad() {
		this._refreshActions();
	}

	onRender() {
		this._refreshActions();
	}

	avaliacao_enviada() {
		this._refreshActions();
	}

	_refreshActions() {
		const actions = [
			{
				label: __("Enviar WhatsApp"),
				icon: "message-circle",
				onClick: () => this.doc.trigger("_openWhatsApp"),
			},
			{
				label: __("Ligar"),
				icon: "phone",
				onClick: () => this.doc.trigger("_startCall"),
			},
		];

		if (!this.doc.avaliacao_enviada) {
			actions.push({
				label: __("Encerrar Atendimento"),
				icon: "check-circle",
				onClick: () => this.doc.trigger("_closeLead"),
			});
		}

		this.actions = actions;
	}

	async _openWhatsApp() {
		let status;
		try {
			status = await call("imunocare_crm_custom.api.whatsapp.whatsapp_window_status", {
				lead: this.doc.name,
			});
		} catch (err) {
			throwError(__("Não foi possível verificar a janela de 24h."));
			return;
		}

		const templates = (status && status.templates) || [];
		const open = !!(status && status.open);

		if (open) {
			const body = window.prompt(__("Mensagem WhatsApp (texto livre):"), "");
			if (!body || !body.trim()) return;
			try {
				await call("imunocare_crm_custom.api.whatsapp.send_whatsapp_from_lead", {
					lead: this.doc.name,
					body: body.trim(),
				});
				toast.success(__("WhatsApp enviado"));
			} catch (err) {
				toast.error(__("Falha ao enviar WhatsApp"));
			}
			return;
		}

		if (!templates.length) {
			throwError(
				__("Janela de 24h fechada e nenhum Message Template aprovado disponível."),
			);
			return;
		}

		const lead = this.doc.name;
		createDialog({
			title: __("Enviar template (janela fechada)"),
			message: __(
				"A janela de 24h está fechada. Escolha um template aprovado para enviar:",
			),
			actions: templates.slice(0, 6).map((t) => ({
				label: t.name,
				onClick: async ({ close }) => {
					try {
						await call(
							"imunocare_crm_custom.api.whatsapp.send_whatsapp_from_lead",
							{ lead, template: t.name },
						);
						close();
						toast.success(__("Template enviado"));
					} catch (err) {
						toast.error(__("Falha ao enviar template"));
					}
				},
			})),
		});
	}

	_startCall() {
		const phone = this.doc.mobile_no || this.doc.phone || "";
		const lead = this.doc.name;
		createDialog({
			title: __("Iniciar chamada"),
			message: __("Conectar chamada para {0}?", [phone || __("(sem telefone)")]),
			actions: [
				{
					label: __("Ligar"),
					theme: "blue",
					onClick: async ({ close }) => {
						try {
							const resp = await call(
								"imunocare_crm_custom.api.twilio.voice_start",
								{ lead },
							);
							close();
							if (resp && resp.call_sid) {
								toast.success(__("Chamada iniciada: {0}", [resp.call_sid]));
							} else {
								toast.success(__("Chamada iniciada"));
							}
						} catch (err) {
							toast.error(__("Falha ao iniciar chamada"));
						}
					},
				},
			],
		});
	}

	_closeLead() {
		const lead = this.doc.name;
		createDialog({
			title: __("Encerrar atendimento"),
			message: __(
				"O atendente atual será registrado como responsável pelo encerramento. Deseja enviar o convite de avaliação?",
			),
			actions: [
				{
					label: __("Encerrar e enviar convite"),
					theme: "green",
					onClick: async ({ close }) => {
						try {
							await call("imunocare_crm_custom.api.survey.close_lead", {
								lead,
								send_invite: 1,
							});
							this.doc.avaliacao_enviada = true;
							close();
							toast.success(__("Atendimento encerrado"));
						} catch (err) {
							toast.error(__("Falha ao encerrar"));
						}
					},
				},
				{
					label: __("Encerrar sem convite"),
					onClick: async ({ close }) => {
						try {
							await call("imunocare_crm_custom.api.survey.close_lead", {
								lead,
								send_invite: 0,
							});
							this.doc.avaliacao_enviada = true;
							close();
							toast.success(__("Atendimento encerrado"));
						} catch (err) {
							toast.error(__("Falha ao encerrar"));
						}
					},
				},
			],
		});
	}
}
