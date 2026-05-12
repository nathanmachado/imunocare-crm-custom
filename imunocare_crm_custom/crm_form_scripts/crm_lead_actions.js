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

	patient() {
		this._refreshActions();
	}

	_refreshActions() {
		const actions = [];

		if (!this.doc.avaliacao_enviada) {
			actions.push({
				label: __("Encerrar Atendimento"),
				icon: "check-circle",
				onClick: () => this.doc.trigger("_closeLead"),
			});
		}

		if (!this.doc.patient) {
			actions.push({
				label: __("Vincular Paciente"),
				icon: "user-check",
				onClick: () => this.doc.trigger("_linkPatient"),
			});
			actions.push({
				label: __("Criar Paciente"),
				icon: "user-plus",
				onClick: () => this.doc.trigger("_createPatient"),
			});
		} else {
			actions.push({
				label: __("Trocar Paciente vinculado"),
				icon: "user",
				onClick: () => this.doc.trigger("_changePatient"),
			});
		}

		this.actions = actions;
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

	async _linkPatient(force = 0) {
		const query = window.prompt(__("Buscar paciente (nome, telefone ou e-mail):"), "");
		if (!query || !query.trim()) return;

		let results;
		try {
			results = await call("imunocare_crm_custom.api.patient.search_patients", {
				query: query.trim(),
				limit: 6,
			});
		} catch (err) {
			toast.error(__("Falha ao buscar pacientes"));
			return;
		}

		if (!results || !results.length) {
			throwError(__("Nenhum paciente encontrado para “{0}”.", [query.trim()]));
			return;
		}

		const lead = this.doc.name;
		createDialog({
			title: __("Selecionar paciente"),
			message: __("Vincular este Lead a um paciente existente:"),
			actions: results.map((p) => {
				const label = [p.first_name, p.last_name].filter(Boolean).join(" ") || p.name;
				const sub = p.mobile || p.phone || p.email || p.name;
				return {
					label: `${label} — ${sub}`,
					onClick: async ({ close }) => {
						try {
							await call("imunocare_crm_custom.api.patient.link_lead_to_patient", {
								lead,
								patient: p.name,
								force,
							});
							this.doc.patient = p.name;
							close();
							toast.success(__("Paciente vinculado"));
						} catch (err) {
							toast.error(__("Falha ao vincular paciente"));
						}
					},
				};
			}),
		});
	}

	_changePatient() {
		const lead = this.doc.name;
		createDialog({
			title: __("Trocar paciente vinculado"),
			message: __(
				"O paciente atual será substituído. Comunicações antigas continuarão visíveis no novo paciente.",
			),
			actions: [
				{
					label: __("Buscar e substituir"),
					theme: "blue",
					onClick: async ({ close }) => {
						close();
						await this.doc.trigger("_linkPatient", 1);
					},
				},
			],
		});
		void lead;
	}

	async _createPatient() {
		const sex = window.prompt(__("Sexo (Male / Female / Other):"), "");
		if (!sex || !sex.trim()) return;

		const lastName = window.prompt(
			__("Sobrenome (deixe vazio para usar o do Lead):"),
			this.doc.last_name || "",
		);
		const dob = window.prompt(__("Data de nascimento (YYYY-MM-DD, opcional):"), "");
		const email = window.prompt(
			__("E-mail (deixe vazio para usar o do Lead):"),
			this.doc.email || "",
		);

		const lead = this.doc.name;
		try {
			const resp = await call("imunocare_crm_custom.api.patient.create_patient_from_lead", {
				lead,
				sex: sex.trim(),
				last_name: (lastName || "").trim() || null,
				dob: (dob || "").trim() || null,
				email: (email || "").trim() || null,
			});
			if (resp && resp.patient) {
				this.doc.patient = resp.patient;
				toast.success(__("Paciente criado: {0}", [resp.patient]));
			} else {
				toast.success(__("Paciente criado"));
			}
		} catch (err) {
			toast.error(__("Falha ao criar paciente"));
		}
	}
}
