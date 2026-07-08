"""Scheduled jobs for AlphaX CRM Automation.

Registered in hooks.scheduler_events (daily_long):
    scan_stale_records  -> follow-up SLA enforcement (notify / reassign)
    run_pdpl_retention  -> anonymize or delete stale leads per retention policy
"""

import frappe
from frappe.utils import add_days, nowdate, getdate

from alphax_crm.crm.utils import get_settings, log_error


# ---------------------------------------------------------------------------
# Stale-deal detection
# ---------------------------------------------------------------------------
def scan_stale_records():
    settings = get_settings()
    if not settings.stale_detection_enabled:
        return
    try:
        _scan("Lead", settings.stale_lead_days or 5, settings)
    except Exception:
        log_error("stale scan: Lead")
    try:
        _scan("Opportunity", settings.stale_opportunity_days or 7, settings)
    except Exception:
        log_error("stale scan: Opportunity")


def _scan(doctype, days, settings):
    cutoff = add_days(nowdate(), -int(days))
    open_status = ["Open", "Replied"] if doctype == "Lead" else ["Open", "Quotation", "Replied"]

    rows = frappe.get_all(
        doctype,
        filters={
            "status": ["in", open_status],
            "modified": ["<", cutoff],
        },
        fields=["name", "owner", "modified"],
        limit_page_length=settings.stale_batch_size or 200,
    )

    action = settings.stale_action or "Notify Owner"
    for row in rows:
        assignee = _current_assignee(doctype, row.name) or row.owner
        if action in ("Notify Owner", "Both"):
            _notify_stale(doctype, row.name, assignee, days)
        if action in ("Reassign", "Both"):
            _reassign(doctype, row.name, settings)


def _current_assignee(doctype, name):
    todos = frappe.get_all(
        "ToDo",
        filters={"reference_type": doctype, "reference_name": name, "status": "Open"},
        fields=["allocated_to"],
        order_by="creation desc",
        limit=1,
    )
    return todos[0].allocated_to if todos else None


def _notify_stale(doctype, name, user, days):
    if not user:
        return
    frappe.get_doc(
        {
            "doctype": "Notification Log",
            "subject": f"AlphaX: {doctype} {name} has had no activity for {days}+ days",
            "for_user": user,
            "type": "Alert",
            "document_type": doctype,
            "document_name": name,
            "from_user": "Administrator",
        }
    ).insert(ignore_permissions=True)


def _reassign(doctype, name, settings):
    pool = [u.strip() for u in (settings.reassign_pool or "").split(",") if u.strip()]
    if not pool:
        return
    # Simple least-loaded pick across the pool.
    counts = {}
    for u in pool:
        counts[u] = frappe.db.count(
            "ToDo", {"allocated_to": u, "status": "Open"}
        )
    target = min(counts, key=counts.get)

    # Clear existing open assignments, then assign to target.
    from frappe.desk.form.assign_to import add as assign_add, clear as assign_clear

    try:
        assign_clear(doctype, name)
        assign_add(
            {
                "assign_to": [target],
                "doctype": doctype,
                "name": name,
                "description": "AlphaX: reassigned (stale follow-up).",
            }
        )
        frappe.get_doc(doctype, name).add_comment(
            "Comment", text=f"AlphaX: reassigned to {target} after inactivity."
        )
    except Exception:
        log_error("reassign")


# ---------------------------------------------------------------------------
# PDPL retention
# ---------------------------------------------------------------------------
def run_pdpl_retention():
    settings = get_settings()
    if not settings.pdpl_retention_enabled:
        return

    days = int(settings.pdpl_retention_days or 365)
    cutoff = add_days(nowdate(), -days)
    action = settings.pdpl_retention_action or "Anonymize"

    # Only act on leads that never converted and have no lawful basis to retain.
    leads = frappe.get_all(
        "Lead",
        filters={
            "status": ["in", ["Lead", "Open", "Do Not Contact", "Junk", "Quotation"]],
            "modified": ["<", cutoff],
        },
        fields=["name", "alphax_lawful_basis"],
        limit_page_length=settings.retention_batch_size or 100,
    )

    for lead in leads:
        # Contract / Legal Obligation bases are retained.
        if (lead.alphax_lawful_basis or "") in ("Contract", "Legal Obligation"):
            continue
        try:
            if action == "Delete":
                frappe.delete_doc("Lead", lead.name, ignore_permissions=True, force=True)
            else:
                _anonymize_lead(lead.name)
        except Exception:
            log_error(f"retention {action}: {lead.name}")

    _retention_sweep_prospects(settings, action)
    frappe.db.commit()


def _retention_sweep_prospects(settings, action):
    """Unconverted prospects are cold-list personal data with no consent —
    they get a shorter retention window than leads (prospect_retention_days,
    default 180). Converted prospects are kept: the Lead carries the data
    and its own retention lifecycle."""
    days = int(settings.get("prospect_retention_days") or 180)
    cutoff = add_days(nowdate(), -days)
    prospects = frappe.get_all(
        "AlphaX Prospect",
        filters={
            "status": ["!=", "Converted"],
            "modified": ["<", cutoff],
            "alphax_pdpl_anonymized": 0,
        },
        pluck="name",
        limit_page_length=settings.retention_batch_size or 100,
    )
    for name in prospects:
        try:
            if action == "Delete":
                frappe.delete_doc("AlphaX Prospect", name, ignore_permissions=True, force=True)
            else:
                frappe.db.set_value(
                    "AlphaX Prospect",
                    name,
                    {
                        "prospect_name": f"Redacted-{name}",
                        "first_name": "Redacted",
                        "last_name": "",
                        "email_id": "",
                        "mobile_no": "",
                        "phone": "",
                        "call_notes": "Redacted under PDPL retention policy.",
                        "alphax_pdpl_anonymized": 1,
                    },
                    update_modified=True,
                )
        except Exception:
            log_error(f"prospect retention {action}: {name}")


def _anonymize_lead(name):
    redactions = {
        "lead_name": f"Redacted-{name}",
        "first_name": "Redacted",
        "last_name": "",
        "email_id": "",
        "mobile_no": "",
        "phone": "",
        "whatsapp_no": "",
        "company_name": "Redacted",
        "alphax_score_breakdown": "Redacted under PDPL retention policy.",
    }
    meta = frappe.get_meta("Lead")
    payload = {k: v for k, v in redactions.items() if meta.has_field(k)}
    payload["alphax_pdpl_anonymized"] = 1
    frappe.db.set_value("Lead", name, payload, update_modified=True)
    frappe.get_doc("Lead", name).add_comment(
        "Comment", text="AlphaX: anonymized under PDPL retention policy."
    )
