"""Activity tracking — keeps follow-up SLAs and scores fresh as
Communications land against Leads / Opportunities."""

import frappe
from frappe.utils import now_datetime

from alphax_crm.crm.utils import get_settings, log_error


def on_communication(doc, method=None):
    ref_dt = doc.get("reference_doctype")
    ref_name = doc.get("reference_name")
    if ref_dt not in ("Lead", "Opportunity") or not ref_name:
        return
    if not frappe.db.exists(ref_dt, ref_name):
        return

    field = "alphax_last_activity"
    try:
        if frappe.get_meta(ref_dt).has_field(field):
            frappe.db.set_value(ref_dt, ref_name, field, now_datetime(), update_modified=False)
    except Exception:
        log_error("activity bump")

    # Inbound message on a Lead -> recompute score so engagement counts.
    if ref_dt == "Lead" and doc.get("sent_or_received") == "Received":
        settings = get_settings()
        if settings.scoring_enabled:
            try:
                from alphax_crm.crm.lead import compute_score

                lead = frappe.get_doc("Lead", ref_name)
                score, breakdown = compute_score(lead, settings)
                frappe.db.set_value(
                    "Lead", ref_name,
                    {"alphax_lead_score": score, "alphax_score_breakdown": breakdown},
                    update_modified=False,
                )
            except Exception:
                log_error("rescore on communication")
