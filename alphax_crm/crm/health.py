"""AlphaX CRM health check: verifies configuration, data and runtime against the approved
Lead workflow spec (A, B WF-01..07, C). Run from AlphaX CRM Settings > Health Check, or
bench --site SITE execute alphax_crm.crm.health.run_health_check
"""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, now_datetime, nowdate

from alphax_crm.crm import workflow
from alphax_crm.crm.utils import ensure_select_option, get_settings

SPEC_TRANSITIONS = [
	("Lead", "Interested"), ("Interested", "Qualified lead"), ("Qualified lead", "Quotation"),
	("Quotation", "Postponed"), ("Quotation", "Contract Under Signing"), ("Quotation", "Lost Quotation"),
	("Postponed", "Won"), ("Postponed", "Lost with reason"), ("Postponed", "Lost Quotation"),
	("Contract Under Signing", "Won"), ("Contract Under Signing", "Lost with reason"), ("Contract Under Signing", "Lost Quotation"),
]
REQUIRED_LEAD_FIELDS = {
	"custom_lead_status": "Lead Status (spec A mapping)",
	"custom_contract": "Contract (WF-06 Won)",
	"won_or_lost_date": "Won/Lost Date (WF-06)",
	"lost_reason": "Lost Reason (WF-06)",
	"detailed_reason": "Detailed Reason (WF-06)",
	"alphax_next_contact_date": "Next Contact Date (WF-05 Postponed)",
}


def _c(area, title, status, detail="", fix=None, count=None):
	return {"area": area, "title": title, "status": status, "detail": detail, "fix": fix, "count": count}


@frappe.whitelist()
def run_health_check():
	frappe.only_for(("System Manager", "Sales Manager"))
	settings = get_settings()
	checks = []
	for fn in (_runtime, _configuration, _data, _followups, _ai):
		try:
			checks += fn(settings)
		except Exception as e:
			checks.append(_c(fn.__name__.strip("_").title(), _("Check failed to run"), "fail", str(e)[:300]))
	summary = {s: sum(1 for c in checks if c["status"] == s) for s in ("ok", "warn", "fail")}
	return {"summary": summary, "checks": checks, "ran_on": str(now_datetime())}


# ------------------------------------------------------------------------------- runtime
def _runtime(settings):
	out = []
	from frappe.utils.scheduler import is_scheduler_disabled

	out.append(_c("Runtime", _("Scheduler"), "fail" if is_scheduler_disabled() else "ok",
		_("Scheduled reminders will not run. Enable with: bench --site SITE enable-scheduler")
		if is_scheduler_disabled() else _("Enabled")))
	try:
		from frappe.utils.background_jobs import get_workers

		n = len(get_workers())
		out.append(_c("Runtime", _("Background workers"), "ok" if n else "fail", _("{0} running").format(n)))
	except Exception:
		out.append(_c("Runtime", _("Background workers"), "warn", _("Could not read the worker list")))
	tz = frappe.db.get_single_value("System Settings", "time_zone")
	out.append(_c("Runtime", _("Time zone"), "ok" if tz == "Asia/Riyadh" else "warn",
		tz if tz == "Asia/Riyadh" else _("{0}: daily rules run at 08:00 of this time zone; the spec expects Asia/Riyadh.").format(tz or "-")))
	jobs = {"alphax_crm.crm.workflow.daily_0800": "WF-04/05 daily 08:00", "alphax_crm.crm.automation.flush_outbox": "outbox",
		"alphax_crm.crm.workflow.wf02_hourly": "WF-02 hourly"}
	missing = [label for method, label in jobs.items() if not frappe.db.exists("Scheduled Job Type", {"method": method})]
	out.append(_c("Runtime", _("Scheduled jobs registered"), "fail" if missing else "ok",
		_("Missing: {0}. Run bench migrate.").format(", ".join(missing)) if missing else _("All registered")))
	email = frappe.db.get_value("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name")
	out.append(_c("Runtime", _("Outgoing email account"), "ok" if email else "fail",
		email or _("No default outgoing Email Account: notifications go in-app only (spec C requires email).")))
	stuck = frappe.db.count("AlphaX Automation Log", {"status": "Queued", "send_after": ["<", add_days(now_datetime(), -1)]})
	failed = frappe.db.count("AlphaX Automation Log", {"status": ["in", ["Failed", "Partly Sent"]], "creation": [">", add_days(now_datetime(), -7)]})
	out.append(_c("Runtime", _("Notification outbox"), "warn" if stuck or failed else "ok",
		_("{0} queued for over a day, {1} failed or partly sent in 7 days (see AlphaX Automation Log)").format(stuck, failed),
		count=stuck + failed))
	errors = frappe.db.count("Error Log", {"method": ["like", "AlphaX%"], "creation": [">", add_days(now_datetime(), -1)]})
	out.append(_c("Runtime", _("AlphaX errors (24h)"), "warn" if errors else "ok", _("{0} in Error Log").format(errors), count=errors))
	return out


# ------------------------------------------------------------------------------- configuration
def _configuration(settings):
	out = []
	meta = frappe.get_meta("Lead")
	for field, label in REQUIRED_LEAD_FIELDS.items():
		has = meta.has_field(field)
		out.append(_c("Configuration", _("Lead field: {0}").format(label), "ok" if has else "fail",
			field if has else _("Field {0} is missing on Lead (add it with Customize Form)").format(field)))

	stages = workflow.approved_stages(settings)
	options = [o.strip() for o in (meta.get_field("status").options or "").split("\n") if o.strip()]
	missing = [s for s in stages if s not in options]
	out.append(_c("Configuration", _("Lead Stage options"), "fail" if missing else "ok",
		_("Missing options: {0}").format(", ".join(missing)) if missing else _("All approved stages selectable"),
		fix="stage_options" if missing else None))
	if meta.has_field("custom_lead_status"):
		st_opts = [o.strip() for o in (meta.get_field("custom_lead_status").options or "").split("\n") if o.strip()]
		need = sorted({st for _s, st in workflow.stage_map(settings)} - set(st_opts))
		out.append(_c("Configuration", _("Lead Status options"), "fail" if need else "ok",
			_("Missing: {0}").format(", ".join(need)) if need else _("OK"), fix="status_options" if need else None))

	current = [(s.lower(), st.lower()) for s, st in workflow.stage_map(settings)]
	spec = [(s.lower(), st.lower()) for s, st in workflow.SPEC_STAGE_MAP]
	diff = [f"{s} → {st}" for s, st in workflow.SPEC_STAGE_MAP if (s.lower(), st.lower()) not in current]
	extra = [f"{s} → {st}" for s, st in workflow.stage_map(settings) if (s.lower(), st.lower()) not in spec]
	out.append(_c("Configuration", _("Stage ↔ Status mapping (spec A)"), "warn" if diff or extra else "ok",
		(_("Missing: {0}").format("; ".join(diff)) if diff else "") + (_(" Not in spec: {0}").format("; ".join(extra)) if extra else "")
		or _("Matches the approved mapping"), fix="stage_map" if diff or extra else None))

	have = {((t.from_stage or "").lower(), (t.to_stage or "").lower()) for t in settings.get("stage_transitions") or []}
	miss_t = [f"{a} → {b}" for a, b in SPEC_TRANSITIONS if (a.lower(), b.lower()) not in have]
	out.append(_c("Configuration", _("Approved transitions (WF-01)"), "warn" if miss_t else "ok",
		_("Missing: {0}").format("; ".join(miss_t)) if miss_t else _("{0} transitions").format(len(have)),
		fix="transitions" if miss_t else None))
	out.append(_c("Configuration", _("Stage control enabled (WF-01)"), "ok" if cint(settings.get("stage_flow_enabled", 1)) else "fail",
		_("The approved transitions apply to all sales and manager roles.")))
	out.append(_c("Configuration", _("Stage protection from ERPNext core"), "ok" if cint(settings.get("protect_lead_stage", 1)) else "warn",
		_("Without it, a submitted quotation or a new Customer silently resets the Lead Stage")))

	from alphax_crm.setup.install import _default_stage_sla_rules, missing_default_sla_rules

	rows = settings.get("stage_sla_rules") or []
	miss_s = missing_default_sla_rules(rows)
	default_keys = {(r[0].lower(), int(r[1])) for r in _default_stage_sla_rules()}
	extra = [f"{r.stage} day {int(r.days or 0)}" for r in rows
		if ((r.stage or "").strip().lower(), int(r.days or 0)) not in default_keys]
	if miss_s:
		detail = _("Missing default rules: {0}. \"Add missing\" adds only these; your existing rows are not changed.").format(
			", ".join(f"{r[0]} day {r[1]}" for r in miss_s))
	else:
		detail = _("{0} rules").format(len(rows))
	if extra:
		detail += " " + _("Also kept (not in the approved defaults): {0}.").format(", ".join(extra))
	out.append(_c("Configuration", _("SLA rules (WF-05)"), "warn" if miss_s else "ok", detail, fix="sla" if miss_s else None))
	approvers = [u for u in workflow.auto.approvers(settings) if frappe.db.get_value("User", u, "email")]
	out.append(_c("Configuration", _("Approvers ({0} role)").format(settings.get("approver_role") or "Sales Manager"),
		"ok" if approvers else "fail", ", ".join(approvers[:6]) or _("No enabled users: escalations have no recipient")))
	cal = workflow.auto.calendar(settings)
	days = ", ".join(workflow.auto.WEEKDAYS[d] for d in sorted(cal.days, key=lambda d: (d + 1) % 7))
	out.append(_c("Configuration", _("Working days & hours (spec C)"), "ok" if cal.days else "fail",
		f"{days}, {cal.start:%H:%M}–{cal.end:%H:%M}; {cal.mode}"))
	out.append(_holidays(settings))
	out += _autofill(settings)
	wf = frappe.db.get_value("Workflow", {"document_type": "Lead", "is_active": 1}, "name")
	paused_state = wf and frappe.db.exists("Workflow Document State", {"parent": wf, "state": "Returned for Correction"})
	out.append(_c("Configuration", _("'Returned for Correction' pause"), "ok" if paused_state else "warn",
		_("Workflow {0}").format(wf) if paused_state else _("No active Lead workflow with that state")))
	for flag, label in (("wf_quotation_check_enabled", "WF-02 quotation check"), ("wf03_confirmation_enabled", "WF-03 confirmation"),
			("wf03_require_valid_till", "WF-03 Valid Till mandatory"), ("wf04_enabled", "WF-04 validity follow-up"),
			("stage_sla_enabled", "WF-05 SLA"), ("closure_controls_enabled", "WF-06 closure controls"),
			("notify_by_email", "Email notifications"), ("business_hours_only", "Business hours only")):
		on = cint(settings.get(flag, 1))
		out.append(_c("Configuration", _(label), "ok" if on else "warn", _("On") if on else _("Off")))
	return out


# ------------------------------------------------------------------------------- data
def _holidays(settings):
	"""Public holidays: which list is used (and the one that follows it), whether the coming 12 months
	contain real public holidays (not only weekends), and whether the calendar runs out soon.
	A Fix button creates next year's list with Saudi public holidays."""
	from alphax_crm.crm import holidays

	title = _("Public holidays")
	hl = workflow.auto.holiday_list(settings)
	need = holidays.next_year_needed(settings)
	fix = "holidays_next_year" if need else None
	if not hl.name:
		return _c("Configuration", title, "warn", _("No Holiday List: Eid and National Day count as working days. "
			"Click Fix to create {0} with Saudi public holidays, or pick a list in Public Holidays (1. General)").format(need),
			fix=fix)
	names = workflow.auto.holiday_lists(settings)
	where = _("{0} (from {1})").format(" → ".join(names), hl.source)
	today = getdate(nowdate())
	to_date = getdate(frappe.db.get_value("Holiday List", names[-1], "to_date") or today)
	if to_date < today:
		return _c("Configuration", title, "warn", _("{0} ended on {1}: every day now counts as a working day. "
			"Click Fix to create {2}").format(where, to_date, need), fix=fix)
	upcoming = frappe.get_all("Holiday", filters={"parent": ["in", names], "weekly_off": 0,
		"holiday_date": ["between", [today, add_days(today, 365)]]}, fields=["holiday_date", "description"], order_by="holiday_date")
	if need:
		left = _("no public holidays left in it") if not upcoming else _("{0} public holidays left").format(len(upcoming))
		return _c("Configuration", title, "warn", _("{0} ends on {1} ({2}). Click Fix to create {3} with the weekly offs, "
			"Founding Day, Eid al-Fitr, Eid al-Adha (estimated dates, confirm when announced) and National Day; AlphaX "
			"moves on to it automatically on 1 January").format(where, to_date, left, need), fix=fix)
	if not upcoming:
		return _c("Configuration", title, "warn", _("{0} has no public holidays in the coming 12 months, only weekly offs. "
			"Click Fix to add Founding Day, Eid al-Fitr, Eid al-Adha (estimated dates, confirm when announced) and "
			"National Day").format(where), fix="holidays_add_public")
	nxt = upcoming[0]
	return _c("Configuration", title, "ok", _("{0}: {1} public holidays in the coming 12 months; next: {2} {3}").format(
		where, len(upcoming), nxt.holiday_date, nxt.description or ""))


def _data(settings):
	out = []
	stages = workflow.approved_stages(settings)
	bad = frappe.db.sql("select status, count(*) from `tabLead` where status not in %(s)s group by status", {"s": stages or [""]})
	n = sum(r[1] for r in bad)
	out.append(_c("Data", _("Leads in non-approved stages"), "warn" if n else "ok",
		", ".join(f"{r[0]}: {r[1]}" for r in bad) or _("None"), count=n))
	q_leads = frappe.get_all("Lead", filters={"status": "Quotation"}, pluck="name", limit=2000)
	no_q = [l for l in q_leads if not workflow.auto.quotations_for_lead(l, {"docstatus": ["<", 2]})]
	out.append(_c("Data", _("At Quotation without a quotation (WF-02)"), "warn" if no_q else "ok",
		", ".join(no_q[:10]) or _("None"), count=len(no_q)))
	meta = frappe.get_meta("Lead")
	won = settings.get("won_stage_value") or "Won"
	cond = []
	if meta.has_field("custom_contract"):
		cond.append("ifnull(custom_contract,'') != %(signed)s")
	if meta.has_field("won_or_lost_date"):
		cond.append("won_or_lost_date is null")
	cnt = 0
	if cond:
		cnt = frappe.db.sql(f"select count(*) from `tabLead` where status=%(won)s and ({' or '.join(cond)})",
			{"won": won, "signed": settings.get("contract_signed_value") or "Signed"})[0][0]
	out.append(_c("Data", _("Won leads missing closure data (WF-06)"), "warn" if cnt else "ok", _("{0} leads").format(cnt), count=cnt))
	lq = settings.get("lost_quotation_stage_value") or "Lost Quotation"
	lq_leads = frappe.get_all("Lead", filters={"status": lq}, pluck="name", limit=2000)
	bad_lq = [l for l in lq_leads if not workflow.auto.quotations_for_lead(l, {"docstatus": 1, "status": "Lost"})]
	out.append(_c("Data", _("Lost Quotation without a lost quotation (WF-06)"), "warn" if bad_lq else "ok",
		", ".join(bad_lq[:10]) or _("None"), count=len(bad_lq)))
	pp = settings.get("postponed_stage_value") or "Postponed"
	no_date = frappe.db.count("Lead", {"status": pp, "alphax_next_contact_date": ["is", "not set"]}) if meta.has_field("alphax_next_contact_date") else 0
	out.append(_c("Data", _("Postponed without Next Contact Date (WF-05)"), "warn" if no_date else "ok", _("{0} leads").format(no_date), count=no_date))
	no_vt = frappe.db.count("Quotation", {"docstatus": 1, "quotation_to": "Lead", "valid_till": ["is", "not set"]})
	out.append(_c("Data", _("Lead quotations without Valid Till (WF-03)"), "warn" if no_vt else "ok", _("{0} quotations").format(no_vt), count=no_vt))
	return out


# ------------------------------------------------------------------------------- follow-ups (0.50)
def _followups(settings):
	"""Follow-ups live on the Lead: linked, booked with reminders, and the reminder job actually running."""
	out = []
	area = _("Follow-ups")
	for dt in ("AlphaX Follow-up", "AlphaX Follow-up Schedule"):
		if not frappe.db.exists("DocType", dt) or not frappe.get_meta(dt).has_field("lead"):
			out.append(_c(area, _("{0}: Lead link").format(_(dt)), "fail", _("Run bench migrate.")))
			return out
	hub = all(frappe.get_meta(dt).has_field("alphax_followup_hub") for dt in ("Lead", "Opportunity"))
	out.append(_c(area, _("Follow-ups panel on Lead and Opportunity"), "ok" if hub else "fail",
		_("At the top of the Follow-ups & Activities tab") if hub else _("Missing: run bench migrate."),
		fix=None if hub else "followup_hub"))
	job = frappe.db.exists("Scheduled Job Type", {"method": "alphax_crm.crm.schedule.run_due_reminders"})
	out.append(_c(area, _("Reminder job (every minute)"), "ok" if job else "fail",
		_("Registered") if job else _("Not registered: run bench migrate."), count=0 if job else 1))
	late = frappe.db.count("AlphaX Follow-up Reminder", {"status": "Pending", "remind_at": ["<", now_datetime() - timedelta(minutes=10)]})
	out.append(_c(area, _("Reminders going out on time"), "fail" if late else "ok",
		_("{0} reminders are more than 10 minutes late: the scheduler or the workers are not running.").format(late) if late
		else _("No backlog"), count=late))
	unlinked = sum(frappe.db.count(dt, {"lead": ["is", "not set"], "reference_doctype": "Lead"})
		for dt in ("AlphaX Follow-up", "AlphaX Follow-up Schedule"))
	out.append(_c(area, _("Follow-ups linked to their Lead"), "warn" if unlinked else "ok",
		_("{0} follow-ups are not yet linked to their Lead (they will not show on it).").format(unlinked) if unlinked else _("All linked"),
		fix="followups_link" if unlinked else None, count=unlinked))
	open_dates = frappe.db.count("AlphaX Follow-up", {"next_follow_up_date": [">=", getdate()], "next_schedule": ["is", "not set"]})
	out.append(_c(area, _("Upcoming next dates with reminders"), "warn" if open_dates else "ok",
		_("{0} upcoming next follow-up dates were logged before 0.50 and have no reminder. Fix books the latest one per record.").format(open_dates)
		if open_dates else _("Every upcoming next date is booked"), fix="followups_book" if open_dates else None, count=open_dates))
	overdue = frappe.db.count("AlphaX Follow-up Schedule", {"status": "Scheduled", "repeat": "Does not repeat",
		"end_datetime": ["<", now_datetime() - timedelta(days=1)]})
	out.append(_c(area, _("Overdue scheduled follow-ups"), "warn" if overdue else "ok",
		_("{0} follow-ups ended over a day ago with no outcome logged (shown as Overdue on the Lead).").format(overdue) if overdue
		else _("None"), count=overdue))
	active = [s for s in workflow.approved_stages(settings) if s not in (settings.get("won_stage_value") or "Won",
		settings.get("lost_quotation_stage_value") or "Lost Quotation", "Lost with reason", "Do Not Contact", "Converted")]
	field = "alphax_next_contact_date" if frappe.get_meta("Lead").has_field("alphax_next_contact_date") else None
	if field and active:
		no_next = frappe.db.sql(f"""select count(*) from `tabLead` l where l.status in %(s)s
			and (l.{field} is null or l.{field} < %(today)s)
			and not exists (select 1 from `tabAlphaX Follow-up Schedule` s where s.lead = l.name and s.status = 'Scheduled')""",
			{"s": active, "today": getdate()})[0][0]
		out.append(_c(area, _("Open Leads with no next follow-up"), "warn" if no_next else "ok",
			_("{0} open Leads have nothing scheduled and no future next contact date.").format(no_next) if no_next else _("None"),
			count=no_next))
	return out


# ------------------------------------------------------------------------------- AI
def _ai(settings):
	out = []
	if not cint(settings.ai_enabled):
		return [_c("AI (WF-07)", _("AI Assist"), "warn", _("Off: lead brief, intent detection, drafts and next action are unavailable"))]
	from alphax_crm.ai import engine

	try:
		engine.complete("You are a connection test.", "Reply OK", feature="health_check", max_tokens=10, timeout=20)
		out.append(_c("AI (WF-07)", _("AI server"), "ok", f"{engine.provider(settings)} · {engine.chat_url(settings)} · {settings.ai_model}"))
	except engine.AIError as e:
		out.append(_c("AI (WF-07)", _("AI server"), "fail", str(e)[:300]))
	out += _ai_models(settings)
	out.append(_c("AI (WF-07)", _("Intent detection on inbound emails"), "ok" if cint(settings.get("ai_intent_detection", 1)) else "warn",
		_("On") if cint(settings.get("ai_intent_detection", 1)) else _("Off")))
	out.append(_c("AI (WF-07)", _("AI write limits (spec C)"), "ok" if not cint(settings.get("ai_next_action_todo")) else "warn",
		_("AI writes only AI fields, timeline notes, notifications and drafts") if not cint(settings.get("ai_next_action_todo"))
		else _("'Create a ToDo for the Lead Owner' is on: the AI also writes ToDos")))
	return out


def _ai_models(settings):
	"""Model self-test results, guide match and free-tier use."""
	from alphax_crm.ai import catalogue
	from alphax_crm.ai.models import status_of

	out = []
	level = {"Passed": "ok", "Partial": "warn", "Not tested": "warn", "Failed": "fail"}
	for target, label, model in (("main", _("Model self-test"), settings.ai_model),
			("fast", _("Fast Model self-test"), settings.get("ai_fast_model"))):
		if not model:
			continue
		st = status_of(settings, target)
		info = catalogue.match(model)
		detail = f"{model}: {_(st)}"
		if info:
			detail += f" · {info['name']} · {_('Arabic')}: {info['arabic']}"
		if st == "Failed":
			detail += " · " + (_("automatic AI is paused") if target == "main" else _("the main model is used instead"))
		elif st == "Not tested":
			detail += " · " + _("run Test Model in AI Assist")
		out.append(_c("AI (WF-07)", label, level.get(st, "warn"), detail))
	out += _ai_setup_advice(settings)
	free = [m for m in (settings.ai_model, settings.get("ai_fast_model")) if m and catalogue.is_free_tier(settings.ai_base_url, m)]
	if free:
		out.append(_c("AI (WF-07)", _("Free-tier hosted model in use"), "warn",
			_("{0}: External; its hosts may keep or train on prompts. PII is always masked and KSA Data Residency Mode "
				"blocks it. Use a self-hosted model for production.").format(", ".join(free))))
	return out


def _ai_setup_advice(settings):
	"""Setup mistakes seen on real sites: quick tunnels in production, model sizes swapped, autofilled secrets."""
	from alphax_crm.ai import catalogue

	out = []
	if catalogue.is_quick_tunnel(settings.ai_base_url):
		out.append(_c("AI (WF-07)", _("Temporary Cloudflare quick tunnel"), "warn",
			_("{0}: stops when the AI machine sleeps or cloudflared closes, changes address on restart, and cuts answers "
				"after ~100 s. Fine for a trial; use a named tunnel or the AlphaX GPU server kit for daily use.").format(
				catalogue.host_of(settings.ai_base_url))))
	main_b, fast_b = catalogue.size_b(settings.ai_model or ""), catalogue.size_b(settings.get("ai_fast_model") or "")
	if main_b and fast_b and fast_b > main_b:
		out.append(_c("AI (WF-07)", _("Fast Model is larger than the main model"), "warn",
			_("Fast Model {0} (~{1}B) is bigger than Model {2} (~{3}B). Swap them: the larger model should do the main "
				"work, the smaller one spell check and translation.").format(settings.get("ai_fast_model"), int(fast_b),
				settings.ai_model, int(main_b))))
	if main_b and main_b < 7:
		out.append(_c("AI (WF-07)", _("Main model is small"), "warn",
			_("{0} (~{1}B) is fine for spell check and translation but unreliable for Ask AI, intent detection and "
				"automations. Use a 27B-class model (see Open Models Guide) as the main model when hardware allows.").format(
				settings.ai_model, main_b if main_b % 1 else int(main_b))))
	return out


AUTOFILL_DATA = {  # fieldname: (label, check that a real value passes)
	"ai_cf_access_client_id": ("CF-Access-Client-Id", lambda v: "@" not in v and v.endswith(".access")),
	"whatsapp_phone_number_id": ("WhatsApp Phone Number ID", lambda v: v.isdigit()),
	"na_api_url": ("National Address API URL", lambda v: v.startswith("http") and "@" not in v),
}
AUTOFILL_SECRETS = {
	"ai_cf_access_client_secret": "CF-Access-Client-Secret", "whatsapp_access_token": "WhatsApp Access Token",
	"whatsapp_app_secret": "WhatsApp App Secret", "na_api_key": "National Address API Key",
}


def _secret(settings, field):
	try:
		return settings.get_password(field, raise_exception=False) or ""
	except Exception:
		return ""


def _autofill_suspects(settings):
	"""Values the browser's password manager typed into the wrong fields: an e-mail or the AI server URL in an
	ID/URL field, or the AI API key copied into another service's secret."""
	ai_url = (settings.get("ai_base_url") or "").strip().rstrip("/")
	ai_key = _secret(settings, "ai_api_key") if settings.get("ai_api_key") else ""
	out = []
	for field, (label, ok) in AUTOFILL_DATA.items():
		v = (settings.get(field) or "").strip()
		if v and (not ok(v) or "@" in v or (ai_url and v.rstrip("/") == ai_url)):
			out.append({"field": field, "label": label, "value": v})
	for field, label in AUTOFILL_SECRETS.items():
		if ai_key and settings.get(field) and _secret(settings, field) == ai_key:
			out.append({"field": field, "label": label, "value": _("the AI API key")})
	return out


def _autofill(settings):
	bad = _autofill_suspects(settings)
	if not bad:
		return []
	return [_c("Configuration", _("Fields filled in by the browser"), "warn",
		_("{0}. The browser's saved password was typed into these fields. Click Fix to clear them "
			"(AlphaX now tells the browser not to autofill this page)").format(
			"; ".join(f"{b['label']} = {b['value']}" for b in bad)), fix="clear_autofill")]


# ------------------------------------------------------------------------------- fixes
@frappe.whitelist(methods=["POST"])
def apply_fix(fix):
	frappe.only_for("System Manager")
	settings = frappe.get_single("AlphaX CRM Settings")
	if fix == "stage_options":
		for s in workflow.approved_stages(settings):
			ensure_select_option("Lead", "status", s, clear_cache=False)
		frappe.clear_cache(doctype="Lead")
	elif fix == "status_options":
		for _s, st in workflow.stage_map(settings):
			ensure_select_option("Lead", "custom_lead_status", st, clear_cache=False)
		frappe.clear_cache(doctype="Lead")
	elif fix == "stage_map":
		settings.set("lead_stage_map", [{"lead_stage": s, "lead_status": st} for s, st in workflow.SPEC_STAGE_MAP])
		settings.save()
	elif fix == "transitions":
		have = {((t.from_stage or "").lower(), (t.to_stage or "").lower()) for t in settings.stage_transitions}
		for a, b in SPEC_TRANSITIONS:
			if (a.lower(), b.lower()) not in have:
				settings.append("stage_transitions", {"from_stage": a, "to_stage": b})
		settings.save()
	elif fix == "sla":
		from alphax_crm.setup.install import missing_default_sla_rules

		for row in missing_default_sla_rules(settings.stage_sla_rules):
			settings.append("stage_sla_rules", dict(zip(("stage", "days", "notify", "require_no_activity", "label",
				"repeat_every_days"), row)))
		settings.save()
	elif fix == "holidays_next_year":
		from alphax_crm.crm import holidays

		year = holidays.next_year_needed(settings)
		if year:
			name = holidays.create_holiday_list(year, settings)
			if not workflow.auto.holiday_list(settings).name:
				settings.holiday_list = name
				settings.save()
	elif fix == "holidays_add_public":
		from alphax_crm.crm import holidays

		for name in workflow.auto.holiday_lists(settings):
			holidays.add_public_holidays(name)
	elif fix == "followup_hub":
		from alphax_crm.setup.install import ensure_followup_hub

		ensure_followup_hub()
	elif fix == "followups_link":
		from alphax_crm.crm.followup_hub import link_all_to_leads

		link_all_to_leads()
	elif fix == "followups_book":
		from alphax_crm.crm.followup_hub import book_open_next_dates

		book_open_next_dates()
	elif fix == "clear_autofill":
		bad = _autofill_suspects(settings)
		for f in bad:
			settings.set(f["field"], None)
		if bad:
			settings.save()
	else:
		frappe.throw(_("Unknown fix {0}").format(fix))
	return run_health_check()
