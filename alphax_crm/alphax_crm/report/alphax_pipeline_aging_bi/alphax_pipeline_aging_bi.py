"""AlphaX Pipeline Aging (BI) — live equivalent of the Excel workbook's
"Current Pipeline Aging" section: how many Leads are sitting in each Lead
Stage right now, and how long they've been there.

Always reflects the current moment (there's no "as of a past date" version
of this one -- that would need reconstructing each Lead's stage history as
of that date from the Log, which the Lead Stage Tracker (BI) report's
period-scoped movement counts already cover). Day-count is time since the
Lead's most recent "Lead Stage" transition (AlphaX Stage Transition Log),
falling back to the Lead's creation date for a lead that has never
transitioned (nothing logged yet).
"""

import frappe
from frappe import _

from alphax_crm.crm.bi_report import get_lead_stage_options, lead_dimension_filters


def execute(filters=None):
    filters = frappe._dict(filters or {})
    stages = get_lead_stage_options()

    conditions = lead_dimension_filters(filters)
    leads = frappe.get_all("Lead", filters=conditions, fields=["name", "status", "creation"],
                            limit_page_length=0)
    lead_names = [l.name for l in leads]

    latest_change = {}
    if lead_names:
        log_rows = frappe.get_all(
            "AlphaX Stage Transition Log",
            filters={
                "reference_doctype": "Lead",
                "field_label": "Lead Stage",
                "reference_name": ["in", lead_names],
            },
            fields=["reference_name", "changed_on"],
            order_by="changed_on desc",
            limit_page_length=0,
        )
        for r in log_rows:
            latest_change.setdefault(r.reference_name, r.changed_on)

    now = frappe.utils.now_datetime()
    by_stage = {}
    for l in leads:
        ref_dt = latest_change.get(l.name) or l.creation
        if not ref_dt:
            continue
        days = (now - frappe.utils.get_datetime(ref_dt)).total_seconds() / 86400.0
        by_stage.setdefault(l.status or _("(not set)"), []).append(days)

    data = []
    for stage in stages:
        days_list = by_stage.pop(stage, [])
        n = len(days_list)
        data.append({
            "stage": stage,
            "leads_in_stage": n,
            "avg_days": round(sum(days_list) / n, 1) if n else 0,
            "oldest_days": round(max(days_list), 1) if n else 0,
        })
    # any stage value present on live Leads but no longer in the field's
    # option list (e.g. retired/renamed since) -- still show it rather than
    # silently dropping those leads from the report.
    for stage, days_list in by_stage.items():
        n = len(days_list)
        data.append({
            "stage": f"{stage} " + str(_("(not in current stage list)")),
            "leads_in_stage": n,
            "avg_days": round(sum(days_list) / n, 1) if n else 0,
            "oldest_days": round(max(days_list), 1) if n else 0,
        })

    data.sort(key=lambda r: r["leads_in_stage"], reverse=True)

    columns = [
        {"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 220},
        {"label": _("Leads In Stage Now"), "fieldname": "leads_in_stage", "fieldtype": "Int", "width": 150},
        {"label": _("Avg Days In Stage"), "fieldname": "avg_days", "fieldtype": "Float", "precision": 1, "width": 150},
        {"label": _("Oldest (Days)"), "fieldname": "oldest_days", "fieldtype": "Float", "precision": 1, "width": 130},
    ]

    total_leads = sum(r["leads_in_stage"] for r in data)
    report_summary = [
        {"label": _("Total Leads (Filtered)"), "value": total_leads, "indicator": "blue"},
    ]

    chart = {
        "data": {
            "labels": [r["stage"] for r in data],
            "datasets": [{"name": _("Leads In Stage Now"), "values": [r["leads_in_stage"] for r in data]}],
        },
        "type": "bar",
    }

    return columns, data, _("Snapshot as of now."), chart, report_summary
