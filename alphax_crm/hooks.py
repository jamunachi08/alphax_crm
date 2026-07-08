app_name = "alphax_crm"
app_title = "AlphaX CRM Automation"
app_publisher = "Neotec Integrated Solutions"
app_description = "Compliance-grade CRM automation for AlphaX on Frappe/ERPNext."
app_email = "support@neotec.ai"
app_license = "Proprietary"
app_version = "0.4.2"

# Requires ERPNext (Lead / Opportunity / CRM doctypes)
required_apps = ["erpnext"]

# ------------------------------------------------------------------------------
# Client scripts
# ------------------------------------------------------------------------------
doctype_js = {"Opportunity": "public/js/opportunity.js", "Lead": "public/js/lead.js"}

# ------------------------------------------------------------------------------
# Install / migrate
# ------------------------------------------------------------------------------
after_install = "alphax_crm.setup.install.after_install"
after_migrate = "alphax_crm.setup.install.after_migrate"

# ------------------------------------------------------------------------------
# Document events  (all heavy AI/network work is enqueued, never inline)
# ------------------------------------------------------------------------------
doc_events = {
    "Lead": {
        "before_insert": "alphax_crm.crm.lead.before_insert",
        "validate": "alphax_crm.crm.lead.validate",
        "after_insert": "alphax_crm.crm.lead.after_insert",
    },
    "Opportunity": {
        "validate": "alphax_crm.crm.opportunity.validate",
        "after_insert": "alphax_crm.crm.opportunity.after_insert",
    },
    "Communication": {
        "after_insert": "alphax_crm.crm.activity.on_communication",
    },
}

# ------------------------------------------------------------------------------
# Scheduler  (stale-deal detection + PDPL retention)
# ------------------------------------------------------------------------------
scheduler_events = {
    "daily_long": [
        "alphax_crm.crm.tasks.scan_stale_records",
        "alphax_crm.crm.tasks.run_pdpl_retention",
    ],
}

# ------------------------------------------------------------------------------
# Fixtures  (any AlphaX-prefixed custom fields / property setters created at
# runtime are re-exported on `bench export-fixtures`; defaults are installed
# programmatically in setup/install.py so a fresh push self-heals on migrate)
# ------------------------------------------------------------------------------
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["name", "like", "%-alphax\\_%"]],
    },
    {
        "dt": "Notification",
        "filters": [["name", "like", "AlphaX %"]],
    },
    {
        "dt": "Workflow",
        "filters": [["name", "like", "AlphaX %"]],
    },
]
