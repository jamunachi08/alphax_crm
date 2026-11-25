"""Common report filters for every AlphaX CRM report (0.47.0).

Each report says which record it counts (its *scope doctype*: Lead, Opportunity, Quotation or AlphaX PreLead).
On top of the report's own filters, every report then gets:

* Lead Stage and Lead Status (multi-select), for any report whose records lead back to a Lead;
* the scope doctype's own Status, when the report counts something other than Leads;
* Date Based On (any date field of the scope doctype, Created On by default) with From / To;
* extra field filters configured in AlphaX CRM Settings > 9.2 (Extra Report Fields), for all reports or
  for one report, on the Lead or on the report's own doctype.

The browser side is public/js/alphax_report_scope.js (one call at the end of each report's .js). On the
server a report either restricts its own query (restrict()) or drops rows afterwards (filter_rows()).
Lead-level filters reach Opportunity / Quotation / PreLead rows through the Lead they came from.
All filter keys start with "ax_" / "axf_" so they never clash with a report's own fields.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from alphax_crm.crm.utils import get_settings, log_error

SCOPE_DOCTYPES = ("Lead", "Opportunity", "Quotation", "AlphaX PreLead")
SLUG = {"Lead": "lead", "Opportunity": "opportunity", "Quotation": "quotation", "AlphaX PreLead": "prelead"}
DOCTYPE_FOR_SLUG = {v: k for k, v in SLUG.items()}
LEAD_STATUS = "custom_lead_status"
NO_MATCH = "__ax_no_match__"
_CACHE = "_ax_scope_cache"


# ============================================================================ configuration
def _settings_flag(settings, field):
	v = settings.get(field)
	return 1 if v is None else cint(v)


def _select_options(doctype, fieldname):
	df = frappe.get_meta(doctype).get_field(fieldname)
	if not df or df.fieldtype != "Select":
		return []
	return [o for o in (df.options or "").split("\n") if o.strip()]


def _date_fields(doctype):
	meta = frappe.get_meta(doctype)
	out = [{"value": "creation", "label": _("Created On")}, {"value": "modified", "label": _("Last Modified")}]
	for df in meta.fields:
		if df.fieldtype in ("Date", "Datetime") and not df.hidden and df.fieldname:
			out.append({"value": df.fieldname, "label": _(df.label or df.fieldname)})
	return out


def configured_fields(settings=None):
	"""Extra Report Fields rows marked as filters, with the doctypes each field exists on."""
	settings = settings or get_settings()
	out = []
	for row in settings.get("monitor_fields") or []:
		fn = (row.fieldname or "").strip()
		if not fn or not cint(row.get("as_filter")):
			continue
		metas = {}
		for dt in SCOPE_DOCTYPES:
			if not frappe.db.exists("DocType", dt):
				continue
			df = frappe.get_meta(dt).get_field(fn)
			if df and df.fieldtype not in ("Table", "Table MultiSelect", "Section Break", "Column Break", "Tab Break",
					"HTML", "Button", "Attach", "Attach Image", "Date", "Datetime"):
				metas[dt] = {"fieldtype": df.fieldtype, "options": df.options, "label": _(row.label or df.label or fn)}
		if metas:
			out.append({"fieldname": fn, "document_type": (row.get("document_type") or "").strip(),
				"report": (row.get("report") or "").strip(), "metas": metas})
	return out


def field_doctype(row, scope_doctype):
	"""Which doctype a configured field filters for a report counting `scope_doctype` (or None)."""
	metas = row["metas"]
	want = row.get("document_type")
	if want:
		return want if want in metas and want in (scope_doctype, "Lead") else None
	if scope_doctype in metas:
		return scope_doctype
	return "Lead" if "Lead" in metas else None


def client_config():
	"""Sent once per session in the boot (frappe.boot.alphax_report_scope)."""
	settings = get_settings()
	doctypes = {}
	for dt in SCOPE_DOCTYPES:
		if frappe.db.exists("DocType", dt):
			doctypes[dt] = {"label": _(dt.replace("AlphaX ", "")), "status_options": _select_options(dt, "status"),
				"date_fields": _date_fields(dt)}
	return {
		"status": _settings_flag(settings, "report_scope_status"),
		"dates": _settings_flag(settings, "report_scope_dates"),
		"lead_stage_options": _select_options("Lead", "status"),
		"lead_status_options": _select_options("Lead", LEAD_STATUS),
		"doctypes": doctypes,
		"fields": configured_fields(settings),
		"slug": SLUG,
	}


def boot_session(bootinfo):
	if frappe.session.user == "Guest":
		return
	try:
		bootinfo.alphax_report_scope = client_config()
	except Exception:
		log_error("report scope boot")


# ============================================================================ reading the filters
def _as_list(value):
	if not value:
		return []
	if isinstance(value, str):
		value = value.strip()
		if value.startswith("["):
			value = frappe.parse_json(value)
		else:
			value = [v.strip() for v in value.split(",")]
	return [v for v in value if v not in (None, "")]


def _field_condition(doctype, fieldname, value):
	df = frappe.get_meta(doctype).get_field(fieldname)
	if not df:
		return None
	if isinstance(value, (list, tuple)):
		values = _as_list(value)
		return ["in", values] if values else None
	if df.fieldtype == "Check":
		return 1 if str(value).lower() in ("1", "yes", "true") else 0
	if df.fieldtype in ("Data", "Small Text", "Text", "Long Text", "Text Editor"):
		return ["like", f"%{value}%"]
	return value


def _date_condition(doctype, filters):
	start, end = filters.get("ax_from_date"), filters.get("ax_to_date")
	if not (start or end):
		return None, None
	field = filters.get("ax_date_field") or "creation"
	meta = frappe.get_meta(doctype)
	if field not in ("creation", "modified"):
		df = meta.get_field(field)
		if not df or df.fieldtype not in ("Date", "Datetime"):
			return None, None
		is_datetime = df.fieldtype == "Datetime"
	else:
		is_datetime = True
	lo = f"{start} 00:00:00" if (start and is_datetime) else start
	hi = f"{end} 23:59:59.999999" if (end and is_datetime) else end
	if start and end:
		return field, ["between", [lo, hi]]
	return field, [">=", lo] if start else ["<=", hi]


def conditions_for(filters, doctype, scope_doctype):
	"""frappe.get_all filters on `doctype` coming from the common filters. Lead-level filters are asked with
	doctype="Lead"; the report's own doctype gets Status, the dates and its own extra fields."""
	filters = filters or {}
	cond = {}
	if doctype == "Lead":
		stages = _as_list(filters.get("ax_lead_stage"))
		if stages:
			cond["status"] = ["in", stages]
		statuses = _as_list(filters.get("ax_lead_status"))
		if statuses and frappe.get_meta("Lead").has_field(LEAD_STATUS):
			cond[LEAD_STATUS] = ["in", statuses]
	if doctype == scope_doctype:
		if doctype != "Lead":
			own = _as_list(filters.get("ax_status"))
			if own and frappe.get_meta(doctype).has_field("status"):
				cond["status"] = ["in", own]
		field, rng = _date_condition(doctype, filters)
		if field:
			cond[field] = rng
	for key, value in filters.items():
		if not key.startswith("axf_") or value in (None, "", []):
			continue
		slug, _sep, fieldname = key[4:].partition("__")
		if DOCTYPE_FOR_SLUG.get(slug) != doctype or not fieldname:
			continue
		c = _field_condition(doctype, fieldname, value)
		if c is not None:
			cond[fieldname] = c
	return cond


def _cache(filters):
	try:
		c = filters.get(_CACHE)
		if c is None:
			c = {}
			filters[_CACHE] = c
		return c
	except Exception:
		return {}


def names(filters, doctype, scope_doctype=None):
	"""Names of `doctype` passing the common filters, or None when none of them applies to it."""
	scope_doctype = scope_doctype or doctype
	if not filters:
		return None
	cache = _cache(filters)
	key = (doctype, scope_doctype)
	if key in cache:
		return cache[key]
	cond = conditions_for(filters, doctype, scope_doctype)
	result = None
	if cond:
		result = set(frappe.get_all(doctype, filters=cond, pluck="name", limit_page_length=0))
	cache[key] = result
	return result


def lead_names(filters, scope_doctype="Lead"):
	return names(filters, "Lead", scope_doctype)


def active(filters, scope_doctype="Lead") -> bool:
	return names(filters, scope_doctype, scope_doctype) is not None or (
		scope_doctype != "Lead" and lead_names(filters, scope_doctype) is not None)


# ============================================================================ Lead behind a record
def leads_for(doctype, record_names):
	"""{record: lead} for Opportunity / Quotation / AlphaX PreLead rows (Lead rows map to themselves)."""
	record_names = [n for n in set(record_names or []) if n]
	if not record_names:
		return {}
	if doctype == "Lead":
		return {n: n for n in record_names}
	out = {}
	if doctype == "Opportunity":
		rows = frappe.get_all("Opportunity", filters={"name": ["in", record_names]},
			fields=["name", "opportunity_from", "party_name"], limit_page_length=0)
		customers = {r.party_name for r in rows if r.opportunity_from == "Customer" and r.party_name}
		cust_lead = dict(frappe.get_all("Customer", filters={"name": ["in", list(customers)]},
			fields=["name", "lead_name"], as_list=True)) if customers else {}
		for r in rows:
			out[r.name] = r.party_name if r.opportunity_from == "Lead" else cust_lead.get(r.party_name)
	elif doctype == "Quotation":
		from alphax_crm.crm.automation import lead_for_quotation

		rows = frappe.get_all("Quotation", filters={"name": ["in", record_names]},
			fields=["name", "quotation_to", "party_name", "opportunity"], limit_page_length=0)
		for r in rows:
			out[r.name] = lead_for_quotation(r)
	elif doctype == "AlphaX PreLead" and frappe.get_meta("Lead").has_field("alphax_prospect"):
		for r in frappe.get_all("Lead", filters={"alphax_prospect": ["in", record_names]},
				fields=["name", "alphax_prospect"], limit_page_length=0):
			out.setdefault(r.alphax_prospect, r.name)
	return out


# ============================================================================ applying it in a report
def allowed(filters, scope_doctype):
	"""Names of `scope_doctype` passing every common filter (own + Lead-level), or None for "no filter"."""
	if not filters:
		return None
	cache = _cache(filters)
	key = ("allowed", scope_doctype)
	if key in cache:
		return cache[key]
	own = names(filters, scope_doctype, scope_doctype)
	result = own
	if scope_doctype != "Lead":
		leads = lead_names(filters, scope_doctype)
		if leads is not None:
			pool = own if own is not None else None
			if pool is None:
				# candidates = records linked to an allowed Lead
				pool = _records_for_leads(scope_doctype, leads)
			mapping = leads_for(scope_doctype, pool)
			result = {n for n in pool if mapping.get(n) in leads}
	cache[key] = result
	return result


def _records_for_leads(doctype, leads):
	if not leads:
		return set()
	leads = list(leads)
	if doctype == "Opportunity":
		out = set(frappe.get_all("Opportunity", filters={"opportunity_from": "Lead", "party_name": ["in", leads]}, pluck="name"))
		customers = frappe.get_all("Customer", filters={"lead_name": ["in", leads]}, pluck="name")
		if customers:
			out |= set(frappe.get_all("Opportunity", filters={"opportunity_from": "Customer",
				"party_name": ["in", customers]}, pluck="name"))
		return out
	if doctype == "Quotation":
		out = set(frappe.get_all("Quotation", filters={"quotation_to": "Lead", "party_name": ["in", leads]}, pluck="name"))
		customers = frappe.get_all("Customer", filters={"lead_name": ["in", leads]}, pluck="name")
		if customers:
			out |= set(frappe.get_all("Quotation", filters={"quotation_to": "Customer",
				"party_name": ["in", customers]}, pluck="name"))
		opps = _records_for_leads("Opportunity", leads)
		if opps:
			out |= set(frappe.get_all("Quotation", filters={"opportunity": ["in", list(opps)]}, pluck="name"))
		return out
	if doctype == "AlphaX PreLead" and frappe.get_meta("Lead").has_field("alphax_prospect"):
		return {p for p in frappe.get_all("Lead", filters={"name": ["in", leads]}, pluck="alphax_prospect") if p}
	return set()


def restrict(filters, scope_doctype, conditions):
	"""Add name-in to a frappe.get_all conditions dict on `scope_doctype`. Returns the dict."""
	ok = allowed(filters, scope_doctype)
	if ok is None:
		return conditions
	wanted = set(ok)
	prev = conditions.get("name")
	if isinstance(prev, (list, tuple)) and len(prev) == 2 and prev[0] == "in":
		wanted &= set(prev[1])
	elif isinstance(prev, str):
		wanted &= {prev}
	conditions["name"] = ["in", list(wanted) or [NO_MATCH]]
	return conditions


def keeps(filters, scope_doctype, name):
	ok = allowed(filters, scope_doctype)
	return ok is None or name in ok


def filter_rows(filters, rows, scope_doctype="Lead", key="lead", doctype_key=None):
	"""Drop report rows whose record (row[key]) fails the common filters. With doctype_key, each row says
	which doctype its record is (follow-up style rows); records of other doctypes are mapped to their Lead."""
	if not filters or not rows:
		return rows
	if not doctype_key:
		ok = allowed(filters, scope_doctype)
		if ok is None:
			return rows
		return [r for r in rows if _get(r, key) in ok]
	leads = lead_names(filters, scope_doctype)
	own = names(filters, scope_doctype, scope_doctype)
	if leads is None and own is None:
		return rows
	by_dt = {}
	for r in rows:
		by_dt.setdefault(_get(r, doctype_key) or scope_doctype, set()).add(_get(r, key))
	lead_map = {dt: leads_for(dt, n) for dt, n in by_dt.items()}
	out = []
	for r in rows:
		dt, name = _get(r, doctype_key) or scope_doctype, _get(r, key)
		if own is not None and dt == scope_doctype and name not in own:
			continue
		if leads is not None and lead_map.get(dt, {}).get(name) not in leads:
			continue
		out.append(r)
	return out


def _get(row, key):
	return row.get(key) if hasattr(row, "get") else getattr(row, key, None)


def describe(filters, scope_doctype="Lead"):
	"""One line for the report message, so a scoped result is never mistaken for the full one."""
	if not filters or not active(filters, scope_doctype):
		return ""
	parts = []
	for k, label in (("ax_lead_stage", _("Lead Stage")), ("ax_lead_status", _("Lead Status")), ("ax_status", _("Status"))):
		v = _as_list(filters.get(k))
		if v:
			parts.append(f"{label}: {', '.join(map(str, v))}")
	if filters.get("ax_from_date") or filters.get("ax_to_date"):
		parts.append(_("{0} {1} – {2}").format(filters.get("ax_date_field") or "creation",
			filters.get("ax_from_date") or "…", filters.get("ax_to_date") or "…"))
	n = sum(1 for k, v in filters.items() if k.startswith("axf_") and v not in (None, "", []))
	if n:
		parts.append(_("{0} extra field filter(s)").format(n))
	return _("Filtered by {0}.").format("; ".join(parts)) if parts else ""
