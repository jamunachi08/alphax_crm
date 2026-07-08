"""Opportunity automation for AlphaX CRM."""

import frappe
from frappe.utils import add_days, nowdate

from alphax_crm.crm.utils import get_settings, log_error


def validate(doc, method=None):
    settings = get_settings()
    if not doc.get("alphax_next_activity_date"):
        days = settings.first_followup_days or 1
        doc.alphax_next_activity_date = add_days(nowdate(), days)


def after_insert(doc, method=None):
    settings = get_settings()
    if settings.ai_enabled and settings.ai_summarize_opportunity:
        frappe.enqueue(
            "alphax_crm.api.ai.summarize_opportunity",
            queue="long",
            opportunity=doc.name,
            enqueue_after_commit=True,
        )


@frappe.whitelist()
def refresh_brief(opportunity):
    """On-demand AI brief, callable from a client-side button."""
    settings = get_settings()
    if not (settings.ai_enabled and settings.ai_summarize_opportunity):
        frappe.throw("AI summarization is disabled in AlphaX CRM Settings.")
    from alphax_crm.api.ai import summarize_opportunity

    return summarize_opportunity(opportunity)
