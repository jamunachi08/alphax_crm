"""Process-controlled Lead Stages (0.46.0).

"Quotation" is set by AlphaX when a quotation for the Lead is submitted (WF-03), and "Lost Quotation"
when a quotation is confirmed Lost (Confirm Lost Quotation / Set as Lost, WF-04/06). Both moves are
written with frappe.db.set_value, so they never pass through Lead.validate. A Lead *save* that moves
the stage into one of them is therefore a manual pick (form dropdown, Lead Status, list quick edit,
Kanban drag, AI "Apply Suggested Stage", REST):

* Quotation      -> allowed only when a quotation is already linked to the Lead (submitted by default).
* Lost Quotation -> never allowed by hand; the user is sent to Confirm Lost Quotation.

Messages come from AlphaX CRM Settings > 4.6 (Arabic and English, both shown). Blank = built-in text.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, escape_html

from alphax_crm.crm import automation as auto
from alphax_crm.crm.utils import get_settings, log_error

STAGE = "status"
STATUS = "custom_lead_status"

TITLE_EN = "Stage set by the process"
TITLE_AR = "هذه المرحلة تُحدَّد من خلال الإجراء"

DEFAULTS = {
	"quotation_en": (
		'The Lead Stage "{{ stage }}" is set automatically when a quotation for this Lead is submitted. '
		"No submitted quotation is linked to {{ lead }} yet. Create it from Create → Quotation and submit it; "
		"the stage will then move on its own."
	),
	"quotation_ar": (
		'تُعيَّن مرحلة "عرض سعر" تلقائياً عند اعتماد عرض سعر مرتبط بهذا العميل المحتمل. '
		"لا يوجد حتى الآن عرض سعر معتمد مرتبط بـ {{ lead }}. أنشئ عرض السعر من إنشاء ← عرض سعر ثم اعتمده، "
		"وستنتقل المرحلة تلقائياً."
	),
	"lost_quotation_en": (
		'The Lead Stage "{{ stage }}" is set only by the process. Use AlphaX AI → Confirm Lost Quotation on this Lead '
		"(or Set as Lost on the quotation) and choose the lost reason; the stage then moves on its own."
	),
	"lost_quotation_ar": (
		'تُعيَّن مرحلة "عرض سعر مفقود" من خلال الإجراء فقط. استخدم AlphaX AI ← تأكيد عرض السعر المفقود في هذا العميل المحتمل '
		'(أو "تعيين كمفقود" في عرض السعر) واختر سبب الفقد، وعندها تنتقل المرحلة تلقائياً.'
	),
}

# settings fieldname for each message key
FIELDS = {
	"quotation_en": "process_stage_msg_quotation_en",
	"quotation_ar": "process_stage_msg_quotation_ar",
	"lost_quotation_en": "process_stage_msg_lost_quotation_en",
	"lost_quotation_ar": "process_stage_msg_lost_quotation_ar",
}


# ---------------------------------------------------------------------------- helpers
def enabled(settings=None) -> bool:
	settings = settings or get_settings()
	val = settings.get("process_stage_guard_enabled")
	return True if val is None else bool(cint(val))


def _quotation_stage(settings) -> str:
	return "Quotation"


def _lost_quotation_stage(settings) -> str:
	return (settings.get("lost_quotation_stage_value") or "Lost Quotation").strip()


def kind_for_stage(stage, settings=None) -> str | None:
	"""'quotation' / 'lost_quotation' / None for any other stage."""
	settings = settings or get_settings()
	s = (stage or "").strip().lower()
	if not s:
		return None
	if s == _quotation_stage(settings).lower():
		return "quotation"
	if s == _lost_quotation_stage(settings).lower():
		return "lost_quotation"
	return None


def has_linked_quotation(lead, settings=None) -> bool:
	if not lead or not frappe.db.exists("Lead", lead):
		return False
	settings = settings or get_settings()
	accept = (settings.get("process_stage_quotation_accepts") or "Submitted quotation").strip()
	docstatus = ["<", 2] if accept.lower().startswith("draft") else 1
	return bool(auto.quotations_for_lead(lead, {"docstatus": docstatus}))


def _render(text, ctx):
	try:
		return frappe.render_template(text, ctx)
	except Exception:
		log_error("process stage message")
		return text


def message(kind, lead=None, stage=None, settings=None) -> dict:
	"""{'title', 'message' (HTML, both languages), 'en', 'ar'} for one blocked stage."""
	settings = settings or get_settings()
	ctx = {
		"lead": lead or _("this Lead"),
		"lead_name": (frappe.db.get_value("Lead", lead, "lead_name") if lead and frappe.db.exists("Lead", lead) else "") or "",
		"stage": stage or (_quotation_stage(settings) if kind == "quotation" else _lost_quotation_stage(settings)),
	}
	ctx = {k: escape_html(str(v)) for k, v in ctx.items()}
	en = _render((settings.get(FIELDS[f"{kind}_en"]) or "").strip() or DEFAULTS[f"{kind}_en"], ctx)
	ar = _render((settings.get(FIELDS[f"{kind}_ar"]) or "").strip() or DEFAULTS[f"{kind}_ar"], ctx)
	ar_block = f'<div dir="rtl" lang="ar" style="text-align:right">{ar}</div>'
	en_block = f'<div dir="ltr" lang="en">{en}</div>'
	arabic_first = (frappe.local.lang or "").lower().startswith("ar")
	blocks = [ar_block, en_block] if arabic_first else [en_block, ar_block]
	title = f"{TITLE_AR} / {TITLE_EN}" if arabic_first else f"{TITLE_EN} / {TITLE_AR}"
	return {"title": title, "message": '<hr style="margin:10px 0">'.join(blocks), "en": en, "ar": ar}


def blocked_kind(lead, stage, settings=None) -> str | None:
	"""Kind of block for moving `lead` into `stage` by hand, or None when allowed."""
	settings = settings or get_settings()
	if not enabled(settings):
		return None
	kind = kind_for_stage(stage, settings)
	if kind == "lost_quotation":
		return kind
	if kind == "quotation" and not has_linked_quotation(lead, settings):
		return kind
	return None


# ---------------------------------------------------------------------------- server guard
def enforce(doc, settings=None):
	"""Lead.validate: refuse a manual move INTO a process-controlled stage."""
	settings = settings or get_settings()
	if doc.flags.get("alphax_system_stage") or not enabled(settings):
		return
	if frappe.flags.in_import or frappe.flags.in_patch or frappe.flags.in_install or frappe.flags.in_migrate:
		return  # historical data loads and upgrades keep their stored stages
	new = (doc.get(STAGE) or "").strip()
	old = "" if doc.is_new() else (frappe.db.get_value("Lead", doc.name, STAGE) or "").strip()
	if not new or new.lower() == old.lower():
		return  # not entering: Leads already at the stage stay editable
	kind = blocked_kind(None if doc.is_new() else doc.name, new, settings)
	if not kind:
		return
	m = message(kind, None if doc.is_new() else doc.name, new, settings)
	frappe.throw(m["message"], title=m["title"])


# ---------------------------------------------------------------------------- form check
@frappe.whitelist()
def check_stage_selection(lead=None, stage=None, lead_status=None, current_stage=None):
	"""Called by the Lead form when Lead Stage (or Lead Status) changes, so the user is told at once.
	The save is guarded again by enforce()."""
	if lead and not frappe.has_permission("Lead", "read", lead):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	settings = get_settings()
	if not stage and lead_status:
		from alphax_crm.crm.workflow import stage_for_status

		stage = stage_for_status(lead_status, current_stage, settings)
	saved = (frappe.db.get_value("Lead", lead, STAGE) or "") if lead and frappe.db.exists("Lead", lead) else ""
	if not stage or saved.strip().lower() == stage.strip().lower():
		return {"allowed": 1, "stage": stage}
	kind = blocked_kind(lead if saved else None, stage, settings)
	if not kind:
		return {"allowed": 1, "stage": stage}
	return {"allowed": 0, "stage": stage, "kind": kind, **message(kind, lead if saved else None, stage, settings)}


@frappe.whitelist()
def preview_messages():
	"""Settings page preview of both messages as users will see them."""
	frappe.only_for(("System Manager", "Sales Manager"))
	settings = get_settings()
	return {k: message(k, None, None, settings) for k in ("quotation", "lost_quotation")}
