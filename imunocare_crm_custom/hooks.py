app_name = "imunocare_crm_custom"
app_title = "Imunocare CRM Custom"
app_publisher = "Imunocare"
app_description = "Personalização do Frappe CRM: WhatsApp Business e integração Healthcare"
app_email = "tech@imunocare.com.br"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "imunocare_crm_custom",
# 		"logo": "/assets/imunocare_crm_custom/logo.png",
# 		"title": "Imunocare CRM Custom",
# 		"route": "/imunocare_crm_custom",
# 		"has_permission": "imunocare_crm_custom.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/imunocare_crm_custom/css/imunocare_crm_custom.css"
# app_include_js = "/assets/imunocare_crm_custom/js/imunocare_crm_custom.js"

# include js, css files in header of web template
# web_include_css = "/assets/imunocare_crm_custom/css/imunocare_crm_custom.css"
# web_include_js = "/assets/imunocare_crm_custom/js/imunocare_crm_custom.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "imunocare_crm_custom/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"CRM Lead": "public/js/crm_lead.js",
	"CRM Call Log": "public/js/crm_call_log.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "imunocare_crm_custom/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "imunocare_crm_custom.utils.jinja_methods",
# 	"filters": "imunocare_crm_custom.utils.jinja_filters"
# }

# Installation
# ------------

after_install = "imunocare_crm_custom.custom_fields.install_custom_fields"
after_migrate = ["imunocare_crm_custom.custom_fields.install_custom_fields"]

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["name", "in", [
			"CRM Lead-imunocare_channel_section",
			"CRM Lead-source_channel",
			"CRM Lead-patient",
			"CRM Lead-column_break_imunocare_contacts",
			"CRM Lead-first_contact_at",
			"CRM Lead-last_contact_at",
			"CRM Lead-avaliacao_enviada",
			"CRM Lead-atendente_encerramento",
			"CRM Lead-encerramento_datetime",
			"CRM Lead-survey_invite_count",
			"CRM Lead-survey_last_invite_at",
			"CRM Lead-inativo_tagged_at",
			"Communication-twilio_section",
			"Communication-twilio_message_sid",
			"Communication-whatsapp_direction",
			"Communication-whatsapp_status",
			"Communication-whatsapp_from",
			"Communication-whatsapp_to",
			"CRM Call Log-patient",
			"CRM Call Log-consent_recorded",
			"Quality Feedback-crm_lead",
			"Quality Feedback-comment",
		]]],
	},
	{
		"dt": "Property Setter",
		"filters": [["name", "=", "Communication-communication_medium-options"]],
	},
	{
		"dt": "CRM Lead Status",
		"filters": [["name", "in", ["Missed Call"]]],
	},
	{
		"dt": "Role",
		"filters": [["role_name", "=", "Imunocare Atendente"]],
	},
	{
		"dt": "Assignment Rule",
		"filters": [["name", "=", "Imunocare CRM Lead Round Robin"]],
	},
	{
		"dt": "Quality Feedback Template",
		"filters": [["name", "=", "Avaliação de Atendimento Imunocare"]],
	},
	{
		"dt": "CRM Form Script",
		"filters": [["name", "=", "Imunocare CRM Lead Actions"]],
	},
]

# Uninstallation
# ------------

# before_uninstall = "imunocare_crm_custom.uninstall.before_uninstall"
# after_uninstall = "imunocare_crm_custom.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "imunocare_crm_custom.utils.before_app_install"
# after_app_install = "imunocare_crm_custom.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "imunocare_crm_custom.utils.before_app_uninstall"
# after_app_uninstall = "imunocare_crm_custom.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "imunocare_crm_custom.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Communication": {
		"before_insert": "imunocare_crm_custom.channels.base.communication_before_insert",
	},
	"CRM Call Log": {
		"after_insert": "imunocare_crm_custom.crm_call_log_hooks.after_insert",
		"on_update": "imunocare_crm_custom.crm_call_log_hooks.on_update",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"imunocare_crm_custom.twilio_integration.tasks.sync_message_templates_approval",
		"imunocare_crm_custom.tasks.leads.tag_inactive_leads",
		"imunocare_crm_custom.tasks.retention.purge_old_recordings",
	],
	"cron": {
		"*/15 * * * *": [
			"imunocare_crm_custom.tasks.survey_retry.retry_survey_invites",
		],
	},
}

# Testing
# -------

# before_tests = "imunocare_crm_custom.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "imunocare_crm_custom.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "imunocare_crm_custom.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["imunocare_crm_custom.utils.before_request"]
# after_request = ["imunocare_crm_custom.utils.after_request"]

# Job Events
# ----------
# before_job = ["imunocare_crm_custom.utils.before_job"]
# after_job = ["imunocare_crm_custom.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"imunocare_crm_custom.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

