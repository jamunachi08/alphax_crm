"""Smart Lead import for AlphaX CRM.

List-view driven CSV/XLSX import that pre-scans every Lead Link field for
missing master records (Industry Type, Lead Source, Territory, ...) and lets
the user decide per master doctype: auto-create the missing records or skip
(blank the field) — then imports row-by-row under savepoints so one bad row
never kills the batch.

Wired from the AlphaX Prospect list view (alphax_prospect_list.js). Files above
SYNC_ROW_LIMIT rows are enqueued on the long queue and the user is notified
over realtime when the job completes. All inserts run under the caller's own
permissions — no ignore_permissions anywhere in this module.
"""

import csv
import io

import frappe
from frappe import _
from frappe.utils import cint

SKIP_FIELDTYPES = {
    "Table", "Table MultiSelect", "Section Break", "Column Break",
    "Tab Break", "HTML", "Button", "Fold", "Heading",
}
SYNC_ROW_LIMIT = 500


# ---------------------------------------------------------------------------
# File reading + header mapping
# ---------------------------------------------------------------------------
def _read_rows(file_url: str) -> list[dict]:
    fdoc = frappe.get_doc("File", {"file_url": file_url})
    content = fdoc.get_content()
    if isinstance(content, str):
        content = content.encode("utf-8")
    fname = (fdoc.file_name or "").lower()
    if fname.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        ws = wb[wb.sheetnames[0]]
        grid = [
            ["" if c is None else str(c).strip() for c in row]
            for row in ws.iter_rows(values_only=True)
        ]
    else:
        text = content.decode("utf-8-sig", errors="replace")
        sample = text[:4096]
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        grid = list(csv.reader(io.StringIO(text), delimiter=delim))
    grid = [r for r in grid if any(str(c).strip() for c in r)]
    if len(grid) < 2:
        frappe.throw(_("File has no data rows"))
    headers = [str(h).strip() for h in grid[0]]
    return [{h: str(c).strip() for h, c in zip(headers, r)} for r in grid[1:]]


def _field_map(headers: list[str], doctype: str = "Lead"):
    """Map file headers to docfields by fieldname or label (case-insensitive)."""
    meta = frappe.get_meta(doctype)
    by_fieldname = {df.fieldname: df for df in meta.fields}
    by_label = {(df.label or "").strip().lower(): df for df in meta.fields if df.label}
    mapped, unmapped = {}, []
    for h in headers:
        df = by_fieldname.get(h) or by_label.get(h.lower())
        if df and df.fieldtype not in SKIP_FIELDTYPES:
            mapped[h] = df
        else:
            unmapped.append(h)
    return mapped, unmapped


# ---------------------------------------------------------------------------
# Source-format normalization
# ---------------------------------------------------------------------------
# Recognized external export headers, per canonical Lead field, in fallback
# priority order (first non-empty value wins). Covers the contact-export
# format customers receive by email ("Work email", "Contact name", ...).
# Extend this table to onboard new export formats — no other change needed.
FIELD_ALIASES = {
    "email_id": ("work email", "work email 2", "private email", "email address"),
    "mobile_no": ("mobile", "mobile 2", "mobile number"),
    "phone": ("phone", "phone 2", "direct phone", "direct phone 2"),
    "company_name": ("company name", "company", "organization"),
    "job_title": ("job title", "title", "designation"),
    "website": ("linkedin profile", "linkedin", "website url"),
    "city": ("contact location - city", "location city"),
    "industry": ("industry",),
}
NAME_ALIASES = ("contact name", "full name", "name")
PHONE_FIELDS = ("mobile_no", "phone", "whatsapp")


def _normalize_phone(value: str) -> str:
    import re

    v = re.sub(r"[^\d+]", "", value or "")
    if not v:
        return ""
    if v.startswith("00"):
        v = "+" + v[2:]
    if v.startswith("966"):
        v = "+" + v
    elif v.startswith("05") and len(v) == 10:
        v = "+966" + v[1:]
    return v


def _transform_rows(rows: list[dict]):
    """Normalize external export rows into Lead-fieldname rows.

    Merges alias columns (e.g. Work email -> Work email 2 -> Private email)
    into their canonical Lead field, first non-empty value winning; a column
    that already direct-maps to the field takes top priority. Splits a
    "Contact name" style column into first/last name and normalizes phone
    numbers. Idempotent: an already-import-ready file passes through
    unchanged. Returns (rows, derived) where derived describes what was
    auto-mapped, for display in the confirmation dialog.
    """
    if not rows:
        return rows, {}
    headers = list(rows[0].keys())
    mapped, _unmapped = _field_map(headers)
    lower = {h.strip().lower(): h for h in headers}
    fieldname_to_header = {}
    for h, df in mapped.items():
        fieldname_to_header.setdefault(df.fieldname, h)

    derived, plan, consumed = {}, {}, set()
    for fieldname, aliases in FIELD_ALIASES.items():
        sources = []
        direct_h = fieldname_to_header.get(fieldname)
        if direct_h:
            sources.append(direct_h)
        alias_hs = [lower[a] for a in aliases if a in lower and lower[a] not in sources]
        if not alias_hs:
            continue
        sources.extend(alias_hs)
        plan[fieldname] = sources
        consumed.update(sources)
        derived[fieldname] = sources

    name_header = None
    if not any(f in fieldname_to_header for f in ("first_name", "last_name", "lead_name")):
        for a in NAME_ALIASES:
            if a in lower:
                name_header = lower[a]
                consumed.add(name_header)
                derived["first_name / last_name"] = [name_header]
                break

    if not plan and not name_header:
        for r in rows:
            for f in PHONE_FIELDS:
                h = fieldname_to_header.get(f)
                if h and r.get(h):
                    r[h] = _normalize_phone(r[h])
        return rows, {}

    passthrough = [h for h in mapped if h not in consumed]
    out = []
    for r in rows:
        new = {h: r.get(h, "") for h in passthrough}
        for fieldname, sources in plan.items():
            new[fieldname] = next((r[s].strip() for s in sources if (r.get(s) or "").strip()), "")
        if name_header:
            parts = (r.get(name_header) or "").split()
            new["first_name"] = parts[0] if parts else ""
            new["last_name"] = " ".join(parts[1:])
        for f in PHONE_FIELDS:
            key = f if f in new else fieldname_to_header.get(f)
            if key and new.get(key):
                new[key] = _normalize_phone(new[key])
        out.append(new)
    return out, derived


# ---------------------------------------------------------------------------
# Pre-scan  (what would this file need?)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def scan_file(file_url: str):
    can_lead = frappe.has_permission("Lead", "create")
    can_prospect = frappe.has_permission("AlphaX Prospect", "create")
    if not (can_lead or can_prospect):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    rows = _read_rows(file_url)
    rows, derived = _transform_rows(rows)
    mapped, unmapped = _field_map(list(rows[0].keys()))
    missing = {}
    for header, df in mapped.items():
        if df.fieldtype != "Link":
            continue
        values = {r.get(header, "") for r in rows} - {""}
        absent = sorted(v for v in values if not frappe.db.exists(df.options, v))
        if absent:
            entry = missing.setdefault(df.options, {"values": set(), "fields": []})
            entry["values"].update(absent)
            entry["fields"].append(df.label or df.fieldname)
    return {
        "total_rows": len(rows),
        "mapped_fields": [df.label or df.fieldname for df in mapped.values()],
        "unmapped_columns": unmapped,
        "derived_fields": {k: v for k, v in derived.items()},
        "can_import_lead": bool(can_lead),
        "missing_masters": {
            dt: {"values": sorted(v["values"]), "fields": v["fields"]}
            for dt, v in missing.items()
        },
    }


# ---------------------------------------------------------------------------
# Master auto-creation  (generic across simple + tree masters)
# ---------------------------------------------------------------------------
def _create_master(doctype: str, value: str):
    meta = frappe.get_meta(doctype)
    doc = frappe.new_doc(doctype)
    autoname = (meta.autoname or "").strip()
    if autoname.startswith("field:"):
        doc.set(autoname.split(":", 1)[1], value)
    elif meta.title_field:
        doc.set(meta.title_field, value)
        doc.name = value
    else:
        doc.name = value
    if meta.is_tree:
        parent_field = f"parent_{frappe.scrub(doctype)}"
        root = frappe.db.get_value(doctype, {parent_field: ("in", ("", None))}, "name")
        if root:
            doc.set(parent_field, root)
    for df in meta.fields:
        if df.reqd and not doc.get(df.fieldname) and df.fieldtype in ("Data", "Small Text", "Text"):
            doc.set(df.fieldname, value)
    doc.insert()
    return doc.name


def _is_duplicate(data: dict) -> bool:
    or_filters = []
    if data.get("email_id"):
        or_filters.append(["email_id", "=", data["email_id"]])
    if data.get("mobile_no"):
        or_filters.append(["mobile_no", "=", data["mobile_no"]])
    if not or_filters:
        return False
    for dt in ("Lead", "AlphaX Prospect"):
        if frappe.get_all(dt, or_filters=or_filters, limit=1):
            return True
    return False


# ---------------------------------------------------------------------------
# Import  (sync for small files, long queue beyond SYNC_ROW_LIMIT)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def run_import(file_url: str, decisions=None, skip_duplicates=1, run_ai=0, default_source=None, import_as="Prospect"):
    target = "AlphaX Prospect" if import_as != "Lead" else "Lead"
    frappe.has_permission(target, "create", throw=True)
    decisions = frappe.parse_json(decisions or "{}")
    rows = _read_rows(file_url)
    if len(rows) > SYNC_ROW_LIMIT:
        frappe.enqueue(
            "alphax_crm.api.lead_import._execute",
            queue="long",
            file_url=file_url,
            decisions=decisions,
            skip_duplicates=cint(skip_duplicates),
            run_ai=cint(run_ai),
            user=frappe.session.user,
            notify=True,
            default_source=default_source,
            target=target,
        )
        return {"queued": True, "total_rows": len(rows)}
    return _execute(
        file_url, decisions, cint(skip_duplicates), cint(run_ai),
        frappe.session.user, default_source=default_source, target=target,
    )


def _execute(file_url, decisions, skip_duplicates, run_ai, user, notify=False, default_source=None, target="Lead"):
    rows = _read_rows(file_url)
    rows, _derived = _transform_rows(rows)
    mapped, _unmapped = _field_map(list(rows[0].keys()), target)

    created_masters = {}
    if target == "Lead":
        for header, df in mapped.items():
            if df.fieldtype != "Link":
                continue
            action = decisions.get(df.options, "skip")
            values = {r.get(header, "") for r in rows} - {""}
            for v in sorted(values):
                if frappe.db.exists(df.options, v):
                    continue
                if action == "create":
                    _create_master(df.options, v)
                    created_masters.setdefault(df.options, []).append(v)
                else:
                    for r in rows:
                        if r.get(header) == v:
                            r[header] = ""

    batch = frappe.utils.now_datetime().strftime("IMP-%Y%m%d-%H%M%S")
    inserted, skipped, failed = [], [], []
    for idx, r in enumerate(rows, start=2):
        data = {df.fieldname: r[h] for h, df in mapped.items() if r.get(h)}
        if not data:
            continue
        if default_source and not data.get("source"):
            data["source"] = default_source
        if skip_duplicates and _is_duplicate(data):
            skipped.append({"row": idx, "reason": _("Duplicate (email/mobile match)")})
            continue
        frappe.db.savepoint("alphax_lead_import_row")
        try:
            doc = frappe.new_doc(target)
            doc.update(data)
            if target == "Lead":
                if not run_ai:
                    doc.flags.alphax_skip_ai = True
            else:
                doc.import_batch = batch
            doc.insert()
            inserted.append(doc.name)
        except Exception as e:
            frappe.db.rollback(save_point="alphax_lead_import_row")
            failed.append({"row": idx, "reason": str(e)})
    frappe.db.commit()

    summary = {
        "inserted": len(inserted),
        "skipped": skipped,
        "failed": failed,
        "created_masters": created_masters,
        "target": target,
    }
    if notify:
        frappe.publish_realtime("alphax_lead_import_done", summary, user=user, after_commit=True)
    return summary
