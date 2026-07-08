"""Prospect qualification for AlphaX CRM.

Converts operator-approved AlphaX Prospect records into ERPNext Leads. The
Lead is inserted normally — dedup, consent stamping, scoring, data-quality
gate and AI classification all fire exactly as for a manually created lead.
Link masters (Industry Type, Lead Source) are created here, at conversion
time, because only genuine leads deserve master records.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from alphax_crm.api.lead_import import _create_master

COPY_FIELDS = (
    "first_name", "last_name", "email_id", "mobile_no", "phone",
    "company_name", "job_title", "website", "city",
)


def _ensure_master(doctype: str, value: str) -> str:
    if not value:
        return ""
    if not frappe.db.exists(doctype, value):
        _create_master(doctype, value)
    return value


@frappe.whitelist()
def convert_to_lead(names):
    frappe.has_permission("Lead", "create", throw=True)
    frappe.has_permission("AlphaX Prospect", "write", throw=True)
    names = frappe.parse_json(names) if isinstance(names, str) else names

    converted, failed = [], []
    for name in names:
        frappe.db.savepoint("alphax_prospect_convert")
        try:
            prospect = frappe.get_doc("AlphaX Prospect", name)
            if prospect.status == "Converted" and prospect.lead:
                failed.append({"prospect": name, "reason": _("Already converted to {0}").format(prospect.lead)})
                continue

            lead = frappe.new_doc("Lead")
            for f in COPY_FIELDS:
                if prospect.get(f):
                    lead.set(f, prospect.get(f))
            lead.industry = _ensure_master("Industry Type", (prospect.industry or "").strip())
            lead.source = _ensure_master("Lead Source", (prospect.source or "").strip())
            lead.insert()

            prospect.db_set(
                {"status": "Converted", "lead": lead.name, "converted_on": now_datetime()},
                notify=True,
            )
            lead.add_comment("Comment", text=f"AlphaX: converted from prospect {name}.")
            converted.append({"prospect": name, "lead": lead.name})
        except Exception as e:
            frappe.db.rollback(save_point="alphax_prospect_convert")
            failed.append({"prospect": name, "reason": str(e)})

    frappe.db.commit()
    return {"converted": converted, "failed": failed}


@frappe.whitelist()
def log_call(name: str, outcome: str, notes: str = ""):
    frappe.has_permission("AlphaX Prospect", "write", throw=True)
    prospect = frappe.get_doc("AlphaX Prospect", name)
    prospect.call_attempts = (prospect.call_attempts or 0) + 1
    prospect.last_call_date = frappe.utils.nowdate()
    if outcome and prospect.status != "Converted":
        prospect.status = outcome
    if notes:
        stamp = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M")
        prospect.call_notes = f"{prospect.call_notes}\n[{stamp}] {notes}".strip() if prospect.call_notes else f"[{stamp}] {notes}"
    prospect.save()
    return {"status": prospect.status, "call_attempts": prospect.call_attempts}
