"""Idempotent setup for AlphaX CRM Automation.

Runs on after_install and (via patch) after_migrate, so pushing the app to
Frappe Cloud and letting it migrate is enough — no bench shell required.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
    ensure_roles()
    setup_custom_fields()
    seed_default_settings()
    ensure_whatsapp_defaults()
    ensure_dq_rules()
    setup_notifications()
    setup_lead_workflow()
    frappe.db.commit()


def after_migrate():
    # Keep config self-healing on every deploy.
    ensure_roles()
    setup_custom_fields()
    ensure_whatsapp_defaults()
    ensure_dq_rules()
    setup_notifications()
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
def ensure_roles():
    """AlphaX Data Entry: collects contacts into AlphaX Prospect only — no
    access to Lead or the rest of the CRM (separation of duties)."""
    if not frappe.db.exists("Role", "AlphaX Data Entry"):
        frappe.get_doc(
            {"doctype": "Role", "role_name": "AlphaX Data Entry", "desk_access": 1}
        ).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Custom fields  (AlphaX-prefixed so the hooks fixture filter picks them up)
# ---------------------------------------------------------------------------
def setup_custom_fields():
    fields = {
        "Lead": [
            {
                "fieldname": "alphax_crm_section",
                "label": "AlphaX CRM",
                "fieldtype": "Section Break",
                "insert_after": "company_name",
                "collapsible": 1,
            },
            {
                "fieldname": "alphax_lead_score",
                "label": "Lead Score",
                "fieldtype": "Int",
                "read_only": 1,
                "in_list_view": 1,
                "insert_after": "alphax_crm_section",
            },
            {
                "fieldname": "alphax_dq_score",
                "label": "Data Completeness %",
                "fieldtype": "Int",
                "read_only": 1,
                "insert_after": "alphax_lead_score",
            },
            {
                "fieldname": "alphax_next_contact_date",
                "label": "Next Contact Date",
                "fieldtype": "Date",
                "insert_after": "alphax_lead_score",
            },
            {
                "fieldname": "alphax_last_activity",
                "label": "Last Activity",
                "fieldtype": "Datetime",
                "read_only": 1,
                "insert_after": "alphax_next_contact_date",
            },
            {
                "fieldname": "alphax_score_breakdown",
                "label": "Score Breakdown",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_last_activity",
            },
            {
                "fieldname": "alphax_dq_report",
                "label": "Data Quality Report",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_score_breakdown",
            },
            {
                "fieldname": "alphax_ai_col",
                "fieldtype": "Column Break",
                "insert_after": "alphax_score_breakdown",
            },
            {
                "fieldname": "alphax_ai_brief",
                "label": "AI Brief",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_ai_col",
            },
            {
                "fieldname": "alphax_ai_draft_reply",
                "label": "AI Draft Reply",
                "fieldtype": "Text",
                "insert_after": "alphax_ai_brief",
            },
            {
                "fieldname": "alphax_inbound_message",
                "label": "Inbound Message",
                "fieldtype": "Small Text",
                "insert_after": "alphax_ai_draft_reply",
            },
            {
                "fieldname": "alphax_pdpl_section",
                "label": "Consent & PDPL",
                "fieldtype": "Section Break",
                "collapsible": 1,
                "insert_after": "alphax_inbound_message",
            },
            {
                "fieldname": "alphax_consent_given",
                "label": "Consent Given",
                "fieldtype": "Check",
                "insert_after": "alphax_pdpl_section",
            },
            {
                "fieldname": "alphax_consent_datetime",
                "label": "Consent Timestamp",
                "fieldtype": "Datetime",
                "read_only": 1,
                "insert_after": "alphax_consent_given",
            },
            {
                "fieldname": "alphax_consent_source",
                "label": "Consent Source",
                "fieldtype": "Data",
                "insert_after": "alphax_consent_datetime",
            },
            {
                "fieldname": "alphax_pdpl_col",
                "fieldtype": "Column Break",
                "insert_after": "alphax_consent_source",
            },
            {
                "fieldname": "alphax_lawful_basis",
                "label": "Lawful Basis",
                "fieldtype": "Select",
                "options": "\nConsent\nContract\nLegitimate Interest\nLegal Obligation",
                "insert_after": "alphax_pdpl_col",
            },
            {
                "fieldname": "alphax_pdpl_anonymized",
                "label": "PDPL Anonymized",
                "fieldtype": "Check",
                "read_only": 1,
                "insert_after": "alphax_lawful_basis",
            },
        ],
        "Opportunity": [
            {
                "fieldname": "alphax_crm_section",
                "label": "AlphaX CRM",
                "fieldtype": "Section Break",
                "collapsible": 1,
                "insert_after": "contact_mobile",
            },
            {
                "fieldname": "alphax_next_activity_date",
                "label": "Next Activity Date",
                "fieldtype": "Date",
                "insert_after": "alphax_crm_section",
            },
            {
                "fieldname": "alphax_last_activity",
                "label": "Last Activity",
                "fieldtype": "Datetime",
                "read_only": 1,
                "insert_after": "alphax_next_activity_date",
            },
            {
                "fieldname": "alphax_ai_col",
                "fieldtype": "Column Break",
                "insert_after": "alphax_last_activity",
            },
            {
                "fieldname": "alphax_ai_brief",
                "label": "AI Brief",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_ai_col",
            },
            {
                "fieldname": "alphax_risk_signal",
                "label": "Risk Signal",
                "fieldtype": "Data",
                "read_only": 1,
                "insert_after": "alphax_ai_brief",
            },
        ],
        "Communication": [
            {
                "fieldname": "alphax_wa_message_id",
                "label": "WhatsApp Message ID",
                "fieldtype": "Data",
                "read_only": 1,
                "no_copy": 1,
                "search_index": 1,
                "insert_after": "message_id",
            },
        ],
    }
    create_custom_fields(fields, ignore_validate=True)


# ---------------------------------------------------------------------------
# Default settings + starter score rules
# ---------------------------------------------------------------------------
def seed_default_settings():
    doc = frappe.get_single("AlphaX CRM Settings")
    if doc.get("score_rules"):
        return  # already configured

    defaults = {
        "scoring_enabled": 1,
        "auto_opportunity_enabled": 1,
        "auto_opportunity_threshold": 70,
        "engagement_points": 2,
        "engagement_cap": 20,
        "dedup_enabled": 1,
        "dedup_fields": "email_id,mobile_no,phone",
        "dedup_action": "Warn",
        "first_followup_days": 1,
        "stale_detection_enabled": 1,
        "stale_lead_days": 5,
        "stale_opportunity_days": 7,
        "stale_action": "Notify Owner",
        "stale_batch_size": 200,
        "default_source": "Campaign",
        "ai_enabled": 0,
        "ai_base_url": "http://localhost:11434",
        "ai_chat_path": "/api/chat",
        "ai_model": "llama3.1",
        "ai_timeout": 60,
        "ai_bilingual": 1,
        "pdpl_retention_enabled": 0,
        "pdpl_retention_days": 365,
        "pdpl_retention_action": "Anonymize",
        "retention_batch_size": 100,
        "data_quality_enabled": 1,
        "dq_enforce_on": "Qualify or Convert",
        "dq_block_incomplete": 1,
        "dq_skip_for_intake": 1,
        "dq_min_completeness": 0,
    }
    for k, v in defaults.items():
        doc.set(k, v)

    starter_rules = [
        ("Source", "Website", 15),
        ("Source", "Referral", 25),
        ("Source", "Campaign", 10),
        ("Status", "Replied", 20),
        ("Industry", "Government", 25),
    ]
    for dim, val, pts in starter_rules:
        if frappe.get_meta("AlphaX CRM Settings").has_field("score_rules"):
            doc.append("score_rules", {"dimension": dim, "match_value": val, "points": pts})

    for r in _default_dq_rules():
        if frappe.get_meta("AlphaX CRM Settings").has_field("dq_rules"):
            doc.append("dq_rules", r)

    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def _default_dq_rules():
    return [
        {"field": "lead_name", "label": "Lead / Contact Name", "requirement": "Required", "validation": "Min Length", "param": "2"},
        {"field": "email_id", "label": "Email", "requirement": "Required", "validation": "Email"},
        {"field": "mobile_no", "label": "Mobile No", "requirement": "Required", "validation": "Saudi Mobile"},
        {"field": "source", "label": "Source", "requirement": "Required", "validation": "Any Value"},
        {"field": "company_name", "label": "Company", "requirement": "Recommended", "validation": "Any Value"},
        {"field": "territory", "label": "Territory", "requirement": "Recommended", "validation": "Any Value"},
        {"field": "industry", "label": "Industry", "requirement": "Recommended", "validation": "Any Value"},
    ]


def ensure_dq_rules():
    """Seed data-quality rules/defaults on existing installs (idempotent).

    Guards against being called before the schema is synced (e.g. a
    pre-model-sync patch phase): if the child doctype or the dq_rules table
    field is not yet available, it does nothing and lets a later post-sync
    pass (after_migrate) seed the rules.
    """
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    if not frappe.db.exists("DocType", "AlphaX Data Quality Rule"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    if not frappe.get_meta("AlphaX CRM Settings").has_field("dq_rules"):
        return

    doc = frappe.get_single("AlphaX CRM Settings")
    changed = False
    dq_defaults = {
        "dq_enforce_on": "Qualify or Convert",
        "dq_block_incomplete": 1,
        "dq_skip_for_intake": 1,
    }
    for f, v in dq_defaults.items():
        if not doc.get(f):
            doc.set(f, v)
            changed = True
    if not (doc.get("dq_rules") or []):
        for r in _default_dq_rules():
            doc.append("dq_rules", r)
        if doc.get("data_quality_enabled") is None:
            doc.data_quality_enabled = 1
        changed = True
    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)


def ensure_whatsapp_defaults():
    """Populate WhatsApp defaults on existing installs without overwriting
    anything the user has already set."""
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    doc = frappe.get_single("AlphaX CRM Settings")
    defaults = {
        "whatsapp_api_version": "v21.0",
        "whatsapp_default_source": "WhatsApp",
        "whatsapp_auto_ack": 1,
        "whatsapp_ack_mode": "Text",
        "whatsapp_ack_language": "en_US",
        "whatsapp_ack_text": (
            "\u0634\u0643\u0631\u0627\u064b \u0644\u062a\u0648\u0627\u0635\u0644\u0643 \u0645\u0639 AlphaX. "
            "\u0633\u064a\u062a\u0648\u0627\u0635\u0644 \u0645\u0639\u0643 \u0623\u062d\u062f \u0645\u0645\u062b\u0644\u064a\u0646\u0627 \u0642\u0631\u064a\u0628\u0627\u064b.\n"
            "Thank you for contacting AlphaX. One of our representatives will reach out shortly."
        ),
    }
    changed = False
    for field, value in defaults.items():
        if not doc.get(field):
            doc.set(field, value)
            changed = True
    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
def setup_notifications():
    _ensure_notification(
        name="AlphaX New Lead Alert",
        subject="AlphaX: New lead {{ doc.lead_name }} (score {{ doc.alphax_lead_score }})",
        document_type="Lead",
        event="New",
        recipients=[{"receiver_by_document_field": "lead_owner"}],
        message="A new lead has been captured and assigned to you.\n\n"
        "Name: {{ doc.lead_name }}\nSource: {{ doc.source }}\n"
        "Score: {{ doc.alphax_lead_score }}\n\nRespond quickly — speed-to-lead drives conversion.",
    )
    _ensure_notification(
        name="AlphaX Follow-up Due",
        subject="AlphaX: Follow-up due for {{ doc.lead_name }}",
        document_type="Lead",
        event="Days Before",
        date_changed="alphax_next_contact_date",
        days_in_advance=0,
        recipients=[{"receiver_by_document_field": "lead_owner"}],
        message="Follow-up is due today for lead {{ doc.lead_name }}.",
    )


def _ensure_notification(name, subject, document_type, event, recipients, message,
                         date_changed=None, days_in_advance=None):
    if frappe.db.exists("Notification", name):
        return
    doc = frappe.new_doc("Notification")
    doc.name = name
    doc.subject = subject
    doc.document_type = document_type
    doc.event = event
    doc.is_standard = 0
    doc.enabled = 1
    doc.channel = "Email"
    doc.message = message
    if date_changed:
        doc.date_changed = date_changed
    if days_in_advance is not None:
        doc.days_in_advance = days_in_advance
    for r in recipients:
        doc.append("recipients", r)
    doc.flags.ignore_permissions = True
    try:
        doc.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="AlphaX CRM: notification setup", message=frappe.get_traceback())


# ---------------------------------------------------------------------------
# Lead workflow (clean stages + SLA discipline)
# ---------------------------------------------------------------------------
def setup_lead_workflow():
    name = "AlphaX Lead Workflow"
    if frappe.db.exists("Workflow", name):
        return

    # State names MUST be valid options of Lead.status (the workflow_state_field).
    states = [
        ("Lead", "Sales User"),
        ("Open", "Sales User"),
        ("Replied", "Sales User"),
        ("Opportunity", "Sales User"),
        ("Converted", "Sales Manager"),
        ("Do Not Contact", "Sales User"),
    ]
    transitions = [
        ("Lead", "Contact", "Open", "Sales User"),
        ("Open", "Reply", "Replied", "Sales User"),
        ("Replied", "Qualify", "Opportunity", "Sales User"),
        ("Opportunity", "Convert", "Converted", "Sales Manager"),
        ("Lead", "Disqualify", "Do Not Contact", "Sales User"),
        ("Open", "Disqualify", "Do Not Contact", "Sales User"),
    ]

    # Ensure the workflow state master rows exist.
    for state, _role in states:
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert(
                ignore_permissions=True
            )
    for _from, action, _to, _role in transitions:
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc(
                {"doctype": "Workflow Action Master", "workflow_action_name": action}
            ).insert(ignore_permissions=True)

    wf = frappe.new_doc("Workflow")
    wf.workflow_name = name
    wf.document_type = "Lead"
    wf.is_active = 1
    wf.workflow_state_field = "status"
    wf.override_status = 0
    for state, role in states:
        wf.append(
            "states",
            {"state": state, "doc_status": "0", "allow_edit": role},
        )
    for frm, action, to, role in transitions:
        wf.append(
            "transitions",
            {"state": frm, "action": action, "next_state": to, "allowed": role, "allow_self_approval": 1},
        )
    wf.flags.ignore_permissions = True
    try:
        wf.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="AlphaX CRM: workflow setup", message=frappe.get_traceback())
