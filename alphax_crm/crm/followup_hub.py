"""Follow-ups, in one place (0.50.0).

Everything about following up a Lead lives on the Lead:

* every follow-up (call, email, WhatsApp, meeting, visit …) is an *AlphaX Follow-up*, including "Log a Call";
* every planned follow-up is an *AlphaX Follow-up Schedule* with reminders (pop-up + email);
* both carry a `lead` link, so work logged on the Lead's Opportunity or PreLead shows on the Lead too;
* the next follow-up date of a logged follow-up is booked automatically as a schedule (date, time, via)
  with the default reminders, so every next date alerts the owner;
* the Lead's Activities tab shows it all (hub()), with one Follow-up menu on the form.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, get_time, getdate, now_datetime, strip_html

from alphax_crm.crm.utils import get_settings, log_error

SCHEDULE = "AlphaX Follow-up Schedule"
FOLLOWUP = "AlphaX Follow-up"
CRM_DOCTYPES = ("Lead", "Opportunity", "AlphaX PreLead")
ONLINE = ("Microsoft Teams", "Zoom", "Google Meet", "Webex")
HUB_FIELD = {"Lead": "alphax_followup_hub", "Opportunity": "alphax_followup_hub", "AlphaX PreLead": "followup_hub_html"}


# ============================================================================ the Lead behind anything
def lead_for(doctype, name):
	if not doctype or not name:
		return None
	try:
		from alphax_crm.crm.automation import lead_of

		lead = lead_of(doctype, name)
		return lead if lead and frappe.db.exists("Lead", lead) else None
	except Exception:
		log_error("follow-up lead link")
		return None


def set_lead(doc):
	"""validate hook for AlphaX Follow-up / Schedule."""
	if doc.meta.has_field("lead"):
		doc.lead = lead_for(doc.reference_doctype, doc.reference_name) or doc.get("lead")


def link_all_to_leads(limit=20000):
	"""Fill `lead` on follow-ups and schedules saved before 0.50 (health-check fix and migrate)."""
	from alphax_crm.crm.automation import lead_owners  # noqa: F401  (warms report_scope import)
	from alphax_crm.crm.report_scope import leads_for

	done = 0
	for dt in (FOLLOWUP, SCHEDULE):
		if not frappe.db.exists("DocType", dt) or not frappe.get_meta(dt).has_field("lead"):
			continue
		rows = frappe.get_all(dt, filters={"lead": ["is", "not set"]}, fields=["name", "reference_doctype", "reference_name"],
			limit_page_length=limit)
		by_dt = {}
		for r in rows:
			by_dt.setdefault(r.reference_doctype, []).append(r)
		for ref_dt, items in by_dt.items():
			mapping = leads_for(ref_dt, [r.reference_name for r in items]) if ref_dt in CRM_DOCTYPES else {}
			groups = {}
			for r in items:
				lead = mapping.get(r.reference_name)
				if lead:
					groups.setdefault(lead, []).append(r.name)
			for lead, names in groups.items():
				for i in range(0, len(names), 500):
					frappe.db.sql(f"update `tab{dt}` set lead=%s where name in %s", (lead, tuple(names[i:i + 500])))
					done += len(names[i:i + 500])
	return done


# ============================================================================ next date -> scheduled follow-up
def platform_for(via):
	via = (via or "Call").strip()
	return {"Phone Call": "Call"}.get(via, via)


def book_next(doc):
	"""After a follow-up is logged with a next date: book it as a schedule with the default reminders.
	The schedule takes over from the old ToDo, so there is one reminder system."""
	if not doc.next_follow_up_date or doc.get("next_schedule") or doc.flags.get("alphax_no_booking"):
		return None
	from alphax_crm.crm import schedule as engine

	settings = get_settings()
	if settings.get("schedule_book_next_dates") is not None and not cint(settings.get("schedule_book_next_dates")):
		return None
	at = get_time(doc.get("next_follow_up_time") or "10:00:00")
	start = datetime.combine(getdate(doc.next_follow_up_date), at)
	platform = platform_for(doc.get("next_follow_up_via"))
	title = (doc.next_action or "").strip() or _("{0} follow-up").format(_(platform))
	sched = frappe.get_doc({
		"doctype": SCHEDULE, "subject": title[:140], "platform": platform, "status": "Scheduled",
		"reference_doctype": doc.reference_doctype, "reference_name": doc.reference_name,
		"organizer": doc.agent or frappe.session.user, "start_datetime": start,
		"end_datetime": start + timedelta(minutes=engine.default_duration(settings)),
		"source_follow_up": doc.name, "time_zone": engine.system_tz(),
		"agenda": frappe.utils.escape_html(doc.next_action or ""),
	})
	sched.insert(ignore_permissions=True)
	frappe.db.set_value(FOLLOWUP, doc.name, "next_schedule", sched.name, update_modified=False)
	return sched.name


def book_open_next_dates(limit=500):
	"""Health-check fix: give upcoming next follow-up dates logged before 0.50 a schedule with reminders.
	Only the latest follow-up of each record counts, and only when that record has nothing scheduled."""
	today = getdate()
	rows = frappe.get_all(FOLLOWUP, filters={"next_follow_up_date": [">=", today], "next_schedule": ["is", "not set"]},
		fields=["name", "reference_doctype", "reference_name", "follow_up_datetime"], order_by="follow_up_datetime desc",
		limit_page_length=limit * 4)
	seen, booked = set(), 0
	for r in rows:
		key = (r.reference_doctype, r.reference_name)
		if key in seen:
			continue
		seen.add(key)
		if frappe.db.exists(SCHEDULE, {"reference_doctype": r.reference_doctype, "reference_name": r.reference_name,
				"status": "Scheduled"}):
			continue
		try:
			doc = frappe.get_doc(FOLLOWUP, r.name)
			if book_next(doc):
				booked += 1
		except Exception:
			log_error("book next follow-up")
		if booked >= limit:
			break
	return booked


# ============================================================================ hub data
def _filters_for(doctype, name, dt):
	"""On a Lead: everything linked to the Lead. Elsewhere: that record only."""
	if doctype == "Lead" and frappe.get_meta(dt).has_field("lead"):
		return [[dt, "lead", "=", name]], [[dt, "reference_doctype", "=", doctype], [dt, "reference_name", "=", name]]
	return [[dt, "reference_doctype", "=", doctype], [dt, "reference_name", "=", name]], None


def _get(dt, doctype, name, fields, extra=None, order_by=None, limit=100):
	main, alt = _filters_for(doctype, name, dt)
	rows = frappe.get_list(dt, filters=main + (extra or []), fields=fields, order_by=order_by, limit_page_length=limit)
	if alt:  # rows saved before the lead link existed
		seen = {r.name for r in rows}
		rows += [r for r in frappe.get_list(dt, filters=alt + (extra or []), fields=fields, order_by=order_by,
			limit_page_length=limit) if r.name not in seen]
	return rows


@frappe.whitelist()
def hub(reference_doctype, reference_name):
	"""Everything the Follow-ups panel shows, in one call."""
	if reference_doctype not in CRM_DOCTYPES:
		frappe.throw(_("Follow-ups are kept for Lead, Opportunity and PreLead."))
	frappe.get_doc(reference_doctype, reference_name).check_permission("read")
	from alphax_crm.crm import schedule as engine
	from alphax_crm.crm.automation import lead_owner_of

	now = now_datetime()
	owner = lead_owner_of(reference_doctype, reference_name)
	sched_fields = ["name", "subject", "platform", "status", "start_datetime", "end_datetime", "all_day", "repeat",
		"repeat_every", "repeat_until", "meeting_link", "location", "organizer", "reference_doctype", "reference_name",
		"completed_follow_up", "source_follow_up"]
	schedules = _get(SCHEDULE, reference_doctype, reference_name, sched_fields, order_by="start_datetime asc", limit=200)
	upcoming, overdue = [], []
	for s in schedules:
		if s.status != "Scheduled":
			continue
		nxt = engine.next_occurrence(s, now - timedelta(hours=12))
		if not nxt:
			continue
		item = dict(s, next_start=str(nxt[0]), next_end=str(nxt[1]),
			when=engine._when(nxt[0], nxt[1], cint(s.all_day)), recurring=(s.repeat or "Does not repeat") != "Does not repeat",
			files=frappe.db.count("File", {"attached_to_doctype": SCHEDULE, "attached_to_name": s.name}),
			organizer_name=frappe.utils.get_fullname(s.organizer) if s.organizer else "",
			elsewhere=(s.reference_doctype, s.reference_name) != (reference_doctype, reference_name))
		(overdue if nxt[1] < now and not item["recurring"] else upcoming).append(item)
	upcoming.sort(key=lambda x: x["next_start"])

	fu_fields = ["name", "follow_up_datetime", "channel", "meeting_type", "direction", "outcome", "duration", "agent",
		"summary", "next_action", "next_follow_up_date", "next_schedule", "reference_doctype", "reference_name"]
	history = []
	for f in _get(FOLLOWUP, reference_doctype, reference_name, fu_fields, order_by="follow_up_datetime desc", limit=100):
		history.append({"kind": "followup", "at": str(f.follow_up_datetime), "channel": f.channel, "meeting_type": f.meeting_type,
			"direction": f.direction, "outcome": f.outcome, "duration": cint(f.duration), "by": frappe.utils.get_fullname(f.agent) if f.agent else "",
			"summary": f.summary or "", "next_action": f.next_action or "", "next_date": str(f.next_follow_up_date or ""),
			"next_schedule": f.next_schedule, "name": f.name, "record": f"{_(f.reference_doctype)} {f.reference_name}",
			"elsewhere": (f.reference_doctype, f.reference_name) != (reference_doctype, reference_name)})
	for s in schedules:
		if s.status in ("Cancelled",) or (s.status == "Completed" and s.completed_follow_up):
			if s.status == "Cancelled":
				history.append({"kind": "cancelled", "at": str(s.start_datetime), "channel": s.platform, "summary": s.subject,
					"name": s.name, "by": frappe.utils.get_fullname(s.organizer) if s.organizer else ""})
	# calls logged with the older "Log a Call" (Communication only), so nothing disappears after the upgrade
	for c in frappe.get_all("Communication", filters={"reference_doctype": reference_doctype, "reference_name": reference_name,
			"communication_medium": "Phone", "subject": ["like", "Call —%"]},
			fields=["name", "communication_date", "subject", "content", "owner"], order_by="communication_date desc", limit_page_length=50):
		history.append({"kind": "call", "at": str(c.communication_date), "channel": "Call", "summary": strip_html(c.content or "")[:300],
			"outcome": c.subject.replace("Call — ", ""), "by": frappe.utils.get_fullname(c.owner), "name": c.name})
	history.sort(key=lambda x: x["at"], reverse=True)

	meta = frappe.get_meta(reference_doctype)
	from alphax_crm.crm.followup import NEXT_DATE_FIELD

	nfield = NEXT_DATE_FIELD.get(reference_doctype)
	row = frappe.db.get_value(reference_doctype, reference_name,
		[f for f in (nfield, "alphax_last_activity", "alphax_last_activity_by", "alphax_last_activity_type") if f and meta.has_field(f)],
		as_dict=True) or {}
	return {
		"lead": lead_for(reference_doctype, reference_name),
		"owner": owner, "owner_name": frappe.utils.get_fullname(owner) if owner else "",
		"next_date": str(row.get(nfield) or "") if nfield else "",
		"last_activity": str(row.get("alphax_last_activity") or ""),
		"last_activity_by": frappe.utils.get_fullname(row.get("alphax_last_activity_by")) if row.get("alphax_last_activity_by") else "",
		"last_activity_type": row.get("alphax_last_activity_type") or "",
		"upcoming": upcoming[:20], "overdue": overdue[:20], "history": history[:120],
		"counts": {"followups": sum(1 for h in history if h["kind"] in ("followup", "call")), "upcoming": len(upcoming), "overdue": len(overdue)},
		"can_write": frappe.has_permission(reference_doctype, "write", reference_name),
	}


# ============================================================================ Lead > Connections
def lead_dashboard(data):
	"""Adds Follow-ups and Scheduled Follow-ups to the Lead's Connections tab."""
	try:
		data = data or {}
		transactions = data.setdefault("transactions", [])
		items = ["AlphaX Follow-up Schedule", "AlphaX Follow-up"]
		if not any(set(items) & set(t.get("items", [])) for t in transactions):
			transactions.insert(0, {"label": _("Follow-ups"), "items": items})
		data.setdefault("fieldname", "lead")
		nsf = data.setdefault("non_standard_fieldnames", {})
		if data.get("fieldname") != "lead":
			for dt in items:
				nsf.setdefault(dt, "lead")
	except Exception:
		log_error("lead dashboard")
	return data


# ============================================================================ follow-up <-> its scheduled next step
def sync_from_followup(doc):
	"""on_update of an AlphaX Follow-up (after the first save): the follow-up is where people change the next step.
	A new date / time / via / next action moves the scheduled follow-up booked from it (same length, reminders
	reset, Teams / Zoom meeting and invitation updated); clearing the date cancels it; a date with nothing booked
	books it. The schedule writes back with db.set_value, so the two never ping-pong."""
	before = doc.get_doc_before_save()
	if not before or doc.flags.get("alphax_from_schedule"):
		return
	fields = ("next_follow_up_date", "next_follow_up_time", "next_follow_up_via", "next_action")
	if all(str(before.get(f) or "") == str(doc.get(f) or "") for f in fields):
		return
	sched = None
	if doc.get("next_schedule") and frappe.db.exists(SCHEDULE, doc.next_schedule):
		sched = frappe.get_doc(SCHEDULE, doc.next_schedule)
		if sched.status != "Scheduled":
			sched = None
	if sched and not doc.next_follow_up_date:
		sched.status = "Cancelled"
		sched.flags.ignore_permissions = True
		sched.save()
		frappe.msgprint(_("Next follow-up date cleared: scheduled follow-up {0} is cancelled.").format(sched.name), alert=True)
		return
	if sched:
		duration = get_datetime(sched.end_datetime) - get_datetime(sched.start_datetime)
		start = datetime.combine(getdate(doc.next_follow_up_date), get_time(doc.get("next_follow_up_time") or "10:00:00"))
		sched.start_datetime, sched.end_datetime = start, start + duration
		if str(before.get("next_follow_up_via") or "") != str(doc.get("next_follow_up_via") or "") and doc.get("next_follow_up_via"):
			sched.platform = platform_for(doc.next_follow_up_via)
		old_title = (before.get("next_action") or "").strip()
		if (doc.next_action or "").strip() and (not old_title or sched.subject == old_title[:140]):
			sched.subject = doc.next_action.strip()[:140]
		sched.flags.ignore_permissions = True
		sched.save()
		frappe.msgprint(_("Scheduled follow-up {0} moved to {1}; reminders reset.").format(
			sched.name, frappe.utils.format_datetime(start, "EEE dd MMM yyyy, h:mm a")), alert=True)
		return
	if doc.next_follow_up_date:
		doc.next_schedule = None
		frappe.db.set_value(FOLLOWUP, doc.name, "next_schedule", None, update_modified=False)
		name = book_next(doc)
		if name:
			frappe.msgprint(_("Next follow-up booked as {0} with reminders.").format(name), alert=True)
	from alphax_crm.crm.followup import NEXT_DATE_FIELD

	field = NEXT_DATE_FIELD.get(doc.reference_doctype)
	if field and doc.next_follow_up_date and frappe.get_meta(doc.reference_doctype).has_field(field):
		frappe.db.set_value(doc.reference_doctype, doc.reference_name, field, doc.next_follow_up_date, update_modified=False)
