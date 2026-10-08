"""Shared engine behind the "AlphaX ... (BI)" report family — the live,
database-backed equivalent of the Lead Tracker BI Excel workbook: one period
engine (Daily/Weekly/.../Yearly + an optional prior-year comparison), reused
by every report in the family instead of each one reinventing it.

Design notes (why this looks the way it does):

* Lead Stage values (the native ``status`` field) are NOT hardcoded here.
  They come from the Select field's own options on whichever site this runs
  on (``get_lead_stage_options``), because this app lets that list be
  extended per-customer (``ensure_select_option`` / Lead Status -> Lead
  Stage Mapping) — a hardcoded stage list would silently go stale the next
  time someone adds a stage.
* "Movement into a stage during a period" comes from AlphaX Stage Transition
  Log (crm/activity.py: record_transition), which already timestamps every
  Lead Stage change — this is the event log a BI report needs; nothing new
  had to be added to capture it.
* The Log only stores reference_name, not the Lead's own dimension fields
  (owner/source/city/business unit/stage), so filtering by those means a
  second, bulk lookup against Lead and an in-Python join — the same
  python-side-aggregation style already used by this app's other reports
  (alphax_sales_pipeline_forecast.py, alphax_stage_duration_report.py)
  rather than a hand-rolled SQL JOIN.
"""

import calendar
import datetime

import frappe


PERIOD_TYPES = ["Daily", "Weekly", "Monthly", "Quarterly", "Half-Yearly", "Yearly"]
COMPARE_MODES = ["None", "Same Period Last Year", "Same Quarter Last Year", "Full Last Year"]


def _to_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return frappe.utils.getdate(v)


def get_period_window(period_type, as_of_date):
    """Mirrors the Excel workbook's Section 2 formulas exactly (same period
    boundaries, same period types) so the two stay comparable."""
    d = _to_date(as_of_date or frappe.utils.today())
    period_type = period_type or "Monthly"

    if period_type == "Daily":
        return d, d
    if period_type == "Weekly":
        start = d - datetime.timedelta(days=d.weekday())  # Monday
        return start, start + datetime.timedelta(days=6)
    if period_type == "Monthly":
        start = d.replace(day=1)
        end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        return start, end
    if period_type == "Quarterly":
        q_start_month = ((d.month - 1) // 3) * 3 + 1
        start = d.replace(month=q_start_month, day=1)
        end_month = q_start_month + 2
        end = start.replace(month=end_month, day=calendar.monthrange(d.year, end_month)[1])
        return start, end
    if period_type == "Half-Yearly":
        start_month = 1 if d.month <= 6 else 7
        start = d.replace(month=start_month, day=1)
        end_month = start_month + 5
        end = start.replace(month=end_month, day=calendar.monthrange(d.year, end_month)[1])
        return start, end
    # Yearly
    return d.replace(month=1, day=1), d.replace(month=12, day=31)


def _shift_years(d, years):
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        # Feb 29 on a non-leap target year
        return d.replace(month=2, day=28, year=d.year - years)


def get_compare_window(compare_mode, years_back, cur_start, cur_end, as_of_date):
    years_back = int(years_back or 1)
    if not compare_mode or compare_mode == "None":
        return None, None
    if compare_mode == "Same Period Last Year":
        return _shift_years(cur_start, years_back), _shift_years(cur_end, years_back)
    if compare_mode == "Same Quarter Last Year":
        d = _to_date(as_of_date)
        q_start_month = ((d.month - 1) // 3) * 3 + 1
        ref = d.replace(month=q_start_month, day=1)
        start = _shift_years(ref, years_back)
        end_month = start.month + 2
        end = start.replace(month=end_month, day=calendar.monthrange(start.year, end_month)[1])
        return start, end
    if compare_mode == "Full Last Year":
        d = _to_date(as_of_date)
        year = d.year - years_back
        return datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    return None, None


def get_lead_stage_options():
    """Every non-blank value configured on Lead's native status field, in
    the order they're defined there -- NOT a hardcoded guess at stage
    names, since this app lets that list be extended per customer."""
    meta = frappe.get_meta("Lead")
    field = meta.get_field("status")
    if not field or not field.options:
        return []
    return [o.strip() for o in field.options.split("\n") if o.strip()]


def get_closure_values(settings=None):
    settings = settings or frappe.get_cached_doc("AlphaX CRM Settings")
    won = (settings.get("won_stage_value") or "Won").strip()
    lost = [s.strip() for s in (settings.get("lost_stage_values") or "").split(",") if s.strip()]
    postponed = (settings.get("postponed_stage_value") or "Postponed").strip()
    return won, lost, postponed


def lead_dimension_filters(filters):
    """Direct frappe.get_all filter dict for querying Lead itself (used for
    the New Leads metric, and for Report 2's current-snapshot stage
    counts). Does not include the Lead Stage (status) filter -- callers
    that need to scope to one stage add "status" themselves."""
    conditions = {}
    for fieldname in ("lead_owner", "source", "city", "custom_business_lead_unit"):
        if filters.get(fieldname):
            conditions[fieldname] = filters.get(fieldname)
    return conditions


def fetch_lead_dim_map(lead_names, extra_fields=None):
    """Bulk-fetch dimension fields for a batch of Lead names, for the
    in-Python join against AlphaX Stage Transition Log / Quotation rows
    (the Log and Quotation don't carry owner/source/city/business-unit
    themselves)."""
    if not lead_names:
        return {}
    fields = ["name", "lead_owner", "source", "city", "custom_business_lead_unit", "status",
              "custom_lead_status", "lost_reason", "detailed_reason"]
    if extra_fields:
        fields = list(dict.fromkeys(fields + extra_fields))
    rows = frappe.get_all(
        "Lead",
        filters={"name": ["in", list(set(lead_names))]},
        fields=fields,
        limit_page_length=0,
    )
    return {r.name: r for r in rows}


def passes_dimension_filters(lead_row, filters):
    """Python-side equivalent of lead_dimension_filters(), applied after the
    bulk Lead lookup above, for rows that originated from the Log/Quotation
    rather than from a direct Lead query."""
    if not lead_row:
        return False
    checks = (
        ("lead_owner", "lead_owner"),
        ("source", "source"),
        ("city", "city"),
        ("custom_business_lead_unit", "custom_business_lead_unit"),
    )
    for filter_key, lead_key in checks:
        want = filters.get(filter_key)
        if want and (lead_row.get(lead_key) or "") != want:
            return False
    return True


def period_label(period_type, cur_start, cur_end, compare_mode, cmp_start, cmp_end, years_back):
    cur = f"{period_type} ({cur_start} to {cur_end})"
    if not compare_mode or compare_mode == "None":
        return cur, None
    cmp_label = f"{compare_mode}, {years_back}y back ({cmp_start} to {cmp_end})"
    return cur, cmp_label


def delta_pct(current, comparison):
    if comparison in (None, 0):
        return None
    return round(((current - comparison) / comparison) * 100.0, 1)


def datetime_range(start, end):
    """("between") bounds for a *Datetime* field (changed_on, creation) given
    plain period-window dates. A bare "2026-10-31" is read as midnight, which
    would silently drop every event later that day -- so the end bound is
    pushed to the last second of that day. Date-only fields (transaction_date,
    won_or_lost_date) don't need this; pass them straight to "between"."""
    if not start:
        return None, None
    return f"{start} 00:00:00", f"{end} 23:59:59"
