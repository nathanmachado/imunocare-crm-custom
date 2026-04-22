frappe.ui.form.on("CRM Call Log", {
	refresh(frm) {
		imunocare_render_recording_player(frm);
	},
});

function imunocare_render_recording_player(frm) {
	if (frm.is_new()) return;
	if (!frm.doc.recording_url) return;

	const proxy_url =
		"/api/method/imunocare_crm_custom.api.twilio.recording_proxy?call_sid=" +
		encodeURIComponent(frm.doc.name);

	const html =
		'<div class="imunocare-recording" style="margin: 0.5rem 0;">' +
		'<label class="control-label">' +
		__("Gravação da chamada") +
		"</label>" +
		'<audio controls preload="none" style="width: 100%;" src="' +
		frappe.utils.escape_html(proxy_url) +
		'"></audio>' +
		"</div>";

	const wrapper = frm.fields_dict.recording_url
		? frm.fields_dict.recording_url.$wrapper
		: null;
	if (wrapper) {
		wrapper.find(".imunocare-recording").remove();
		wrapper.append(html);
	} else {
		frm.dashboard.add_section(html, __("Gravação"));
	}
}
