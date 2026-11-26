"""Follow-up scheduling: Teams-style meetings for Leads, Opportunities and PreLeads (0.49.0).

An *AlphaX Follow-up Schedule* is a planned follow-up: title, platform (Teams / Zoom / Meet / Webex / phone /
on-site …), join link or location, start and end (or all day, in any time zone), optional repeat, attendees,
agenda and attachments. Logging what happened is still an *AlphaX Follow-up*; the two link to each other.

Reminders
---------
Each schedule carries reminder rules ("15 minutes before: pop-up + email", "1 day before: email" …). On save the
rules are expanded into *AlphaX Follow-up Reminder* rows, one per person per occurrence per rule, for the next
HORIZON_DAYS (a daily job extends recurring series). `run_due_reminders` (every minute) sends the email and
pushes the pop-up (real-time to an open desk, plus the bell). A pop-up stays "Due" until the user dismisses it,
so someone who logs in late still sees it; Snooze puts it back in the queue.

Calendar
--------
Each schedule keeps a linked Frappe *Event* (calendar, and the Activities tab of the record), and can email an
.ics invitation with the schedule's attachments to its attendees. Internal attendees get the ERP link and the
Lead Owner; external attendees (clients) get a clean invitation with no internal links.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import (add_months, cint, escape_html, format_datetime, get_datetime, get_url,
	get_url_to_form, getdate, now_datetime, strip_html)

from alphax_crm.crm.utils import get_settings, log_error

SCHEDULE = "AlphaX Follow-up Schedule"
REMINDER = "AlphaX Follow-up Reminder"
NO_REPEAT = "Does not repeat"
WORKING = "Every working day"
OFFSETS = {
	"At start time": 0, "5 minutes before": 5, "10 minutes before": 10, "15 minutes before": 15,
	"30 minutes before": 30, "1 hour before": 60, "2 hours before": 120, "1 day before": 1440,
	"2 days before": 2880, "1 week before": 10080,
}
DEFAULT_RULES = (("15 minutes before", 1, 1), ("1 day before", 0, 1))
LATE_RULE = "Starting soon"
HORIZON_DAYS = 14
MAX_OCCURRENCES = 500
SNOOZE_MINUTES = (5, 10, 15, 30, 60)
ONLINE = {"Microsoft Teams", "Zoom", "Google Meet", "Webex"}
ICS_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
TITLE_FIELDS = ("lead_name", "company_name", "title", "customer_name", "prospect_name", "party_name")
EMAIL_FIELDS = ("email_id", "contact_email", "email", "email_address")


# ============================================================================ settings
def default_rules(settings=None):
	settings = settings or get_settings()
	rows = [r for r in (settings.get("schedule_default_reminders") or []) if r.get("remind_before")]
	if rows:
		return [{"remind_before": r.remind_before, "popup": cint(r.popup), "email": cint(r.email)} for r in rows]
	return [{"remind_before": b, "popup": p, "email": e} for b, p, e in DEFAULT_RULES]


def default_duration(settings=None):
	settings = settings or get_settings()
	return cint(settings.get("schedule_default_duration")) or 30


def _flag(settings, field, default=1):
	v = settings.get(field)
	return default if v is None else cint(v)


# ============================================================================ time zones
def system_tz():
	try:
		from frappe.utils import get_system_timezone

		return get_system_timezone()
	except Exception:
		return frappe.db.get_single_value("System Settings", "time_zone") or "Asia/Riyadh"


def convert(dt, from_tz, to_tz):
	"""Naive datetime in from_tz -> naive datetime in to_tz."""
	if not dt:
		return dt
	dt = get_datetime(dt)
	if not from_tz or not to_tz or from_tz == to_tz:
		return dt
	from zoneinfo import ZoneInfo

	return dt.replace(tzinfo=ZoneInfo(from_tz)).astimezone(ZoneInfo(to_tz)).replace(tzinfo=None)


def _valid_tz(tz):
	if not tz:
		return None
	try:
		from zoneinfo import ZoneInfo

		ZoneInfo(tz)
		return tz
	except Exception:
		return None


# ============================================================================ recurrence
def _step(repeat, every, start, i):
	if repeat == "Daily":
		return start + timedelta(days=every * i)
	if repeat == WORKING:
		return start + timedelta(days=i)
	if repeat == "Weekly":
		return start + timedelta(weeks=every * i)
	if repeat == "Monthly":
		return get_datetime(add_months(start, every * i))
	return start


def occurrences(doc, start_from=None, until=None):
	"""[(start, end)] of the schedule that end on/after start_from and start on/before until."""
	start = get_datetime(doc.get("start_datetime"))
	end = get_datetime(doc.get("end_datetime") or start)
	if end < start:
		end = start
	duration = end - start
	start_from = get_datetime(start_from) if start_from else start
	until = get_datetime(until) if until else start + timedelta(days=366)
	repeat = doc.get("repeat") or NO_REPEAT
	if repeat == NO_REPEAT:
		return [(start, end)] if end >= start_from and start <= until else []
	every = max(1, cint(doc.get("repeat_every")) or 1)
	last = datetime.combine(getdate(doc.repeat_until), time(23, 59, 59)) if doc.get("repeat_until") else None
	cal = None
	if repeat == WORKING:
		from alphax_crm.crm import automation as auto

		cal = auto.calendar()
	# jump close to start_from instead of walking from a start long ago
	i = 0
	gap = (start_from - duration) - start
	if gap.total_seconds() > 0:
		if repeat in ("Daily", WORKING):
			i = max(0, int(gap.days // (every if repeat == "Daily" else 1)) - 1)
		elif repeat == "Weekly":
			i = max(0, int(gap.days // (7 * every)) - 1)
		elif repeat == "Monthly":
			i = max(0, int(gap.days // (28 * every)) - 2)
	out, guard = [], 0
	while guard < MAX_OCCURRENCES * 3 and len(out) < MAX_OCCURRENCES:
		guard += 1
		cur = _step(repeat, every, start, i)
		i += 1
		if cur > until or (last and cur > last):
			break
		if cal is not None:
			from alphax_crm.crm import automation as auto

			if not auto.is_working_day(cur.date(), cal):
				continue
		if cur + duration >= start_from:
			out.append((cur, cur + duration))
	return out


def next_occurrence(doc, after=None):
	occ = occurrences(doc, after or now_datetime(), (after or now_datetime()) + timedelta(days=400))
	return occ[0] if occ else None


# ============================================================================ document hooks
def validate_schedule(doc):
	settings = get_settings()
	doc.organizer = doc.organizer or frappe.session.user
	doc.platform = doc.platform or settings.get("schedule_default_platform") or "Microsoft Teams"
	doc.repeat = doc.repeat or NO_REPEAT
	doc.repeat_every = max(1, cint(doc.repeat_every) or 1)
	if not doc.start_datetime:
		frappe.throw(_("Start time is required."))
	start = get_datetime(doc.start_datetime)
	end = get_datetime(doc.end_datetime) if doc.end_datetime else None
	if cint(doc.all_day):
		start = datetime.combine(start.date(), time(0, 0))
		end = datetime.combine((end or start).date(), time(23, 59, 59))
	if not end or end <= start:
		end = start + timedelta(minutes=default_duration(settings))
	doc.start_datetime, doc.end_datetime = start, end
	if doc.repeat != NO_REPEAT and doc.repeat_until and getdate(doc.repeat_until) < start.date():
		frappe.throw(_("The repeat end date is before the first meeting."))
	if not doc.get("reminders"):
		for r in default_rules(settings):
			doc.append("reminders", r)
	if doc.meeting_link and not doc.meeting_link.lower().startswith(("http://", "https://")):
		doc.meeting_link = "https://" + doc.meeting_link.strip()
	seen = set()
	for a in list(doc.get("attendees") or []):
		if a.attendee_type == "Internal" and a.user:
			a.email = a.email or frappe.db.get_value("User", a.user, "email")
			a.full_name = a.full_name or frappe.utils.get_fullname(a.user)
		key = (a.email or a.user or "").strip().lower()
		if not key or key in seen:
			doc.remove(a)
			continue
		seen.add(key)
	from alphax_crm.crm.automation import lead_owner_of
	from alphax_crm.crm.followup_hub import set_lead

	set_lead(doc)
	doc.lead_owner = lead_owner_of(doc.reference_doctype, doc.reference_name) or doc.lead_owner
	if doc.status == "Completed" and not doc.completed_on:
		doc.completed_on = now_datetime()
	before = doc.get_doc_before_save() if not doc.is_new() else None
	doc.flags.ax_time_changed = bool(doc.is_new() or not before or any(
		str(before.get(f) or "") != str(doc.get(f) or "")
		for f in ("start_datetime", "end_datetime", "all_day", "repeat", "repeat_every", "repeat_until",
			"meeting_link", "location", "subject", "agenda", "platform"))
		or _people(before) != _people(doc))
	doc.flags.ax_was_scheduled = bool(before and before.status == "Scheduled")


def _people(doc):
	return sorted(((a.email or a.user or "").lower(), a.attendance or "") for a in (doc.get("attendees") or []))


def on_schedule_update(doc):
	from alphax_crm.crm import meeting_connect

	# Teams / Zoom / Meet / Webex first, so the join link is in the Event, reminders and invitation.
	platform_before, meeting_before = doc.get("online_meeting_platform"), doc.get("online_meeting_id")
	meeting_connect.sync(doc)
	for step, fn in (("event", sync_event), ("reminders", rebuild_reminders), ("next date", push_next_date),
			("source link", link_source_followup)):
		try:
			fn(doc)
		except Exception:
			log_error(f"follow-up schedule {step}")
	try:
		if doc.status == "Scheduled":
			platform_invites = meeting_connect.provider_handles_invites(doc.platform, doc.online_meeting_id)
			if cint(doc.send_invitation) and not platform_invites and (doc.flags.ax_time_changed or not doc.invitation_sent_on):
				send_invitation(doc)
		elif doc.status == "Cancelled" and doc.flags.ax_was_scheduled and doc.invitation_sent_on:
			if not meeting_connect.provider_handles_invites(platform_before, meeting_before):
				send_invitation(doc, method="CANCEL")
	except Exception:
		log_error("follow-up schedule invitation")


def link_source_followup(doc):
	"""Scheduled from a logged follow-up (Save & Schedule Follow-up): the follow-up points to it."""
	if doc.source_follow_up and frappe.db.exists("AlphaX Follow-up", doc.source_follow_up) \
			and not frappe.db.get_value("AlphaX Follow-up", doc.source_follow_up, "next_schedule"):
		frappe.db.set_value("AlphaX Follow-up", doc.source_follow_up, "next_schedule", doc.name, update_modified=False)


def on_schedule_trash(doc):
	frappe.db.delete(REMINDER, {"schedule": doc.name})
	if doc.event and frappe.db.exists("Event", doc.event):
		frappe.delete_doc("Event", doc.event, ignore_permissions=True, force=True)


# ============================================================================ next contact date
def push_next_date(doc):
	"""The meeting is the next contact: its next occurrence becomes the record's next follow-up date."""
	if doc.status != "Scheduled":
		return
	nxt = next_occurrence(doc)
	if not nxt:
		return
	day = nxt[0].date()
	if doc.source_follow_up and frappe.db.exists("AlphaX Follow-up", doc.source_follow_up):
		# keep the follow-up it was booked from in step: date, time and channel
		values = {"next_follow_up_date": day}
		meta = frappe.get_meta("AlphaX Follow-up")
		if meta.has_field("next_follow_up_time") and not cint(doc.all_day):
			values["next_follow_up_time"] = nxt[0].time()
		if meta.has_field("next_follow_up_via") and doc.platform:
			values["next_follow_up_via"] = "Call" if doc.platform == "Phone Call" else doc.platform
		frappe.db.set_value("AlphaX Follow-up", doc.source_follow_up, values, update_modified=False)
	from alphax_crm.crm.followup import NEXT_DATE_FIELD

	field = NEXT_DATE_FIELD.get(doc.reference_doctype)
	if field and frappe.get_meta(doc.reference_doctype).has_field(field) and frappe.db.exists(doc.reference_doctype, doc.reference_name):
		frappe.db.set_value(doc.reference_doctype, doc.reference_name, field, day, update_modified=False)


# ============================================================================ reminders
def recipients(doc, settings=None):
	settings = settings or get_settings()
	users = [doc.organizer]
	if _flag(settings, "schedule_remind_lead_owner") and doc.lead_owner:
		users.append(doc.lead_owner)
	users += [a.user for a in (doc.get("attendees") or []) if a.attendee_type == "Internal" and a.user]
	out = []
	for u in users:
		if u and u not in out and u not in ("Guest",) and frappe.db.get_value("User", u, "enabled"):
			out.append(u)
	return out


def rebuild_reminders(doc, now=None):
	"""Replace the schedule's queued reminders with ones matching its current time, people and rules.
	Reminders already shown or dismissed for an occurrence are kept, so a save never repeats them."""
	now = get_datetime(now or now_datetime())
	frappe.db.delete(REMINDER, {"schedule": doc.name, "status": "Pending"})
	kept = frappe.get_all(REMINDER, filters={"schedule": doc.name, "status": ["!=", "Pending"]},
		fields=["name", "status", "user", "occurrence_start", "remind_before"], limit_page_length=0)
	if doc.status != "Scheduled":
		for r in kept:
			if r.status == "Due":
				frappe.db.set_value(REMINDER, r.name, "status", "Cancelled", update_modified=False)
		return 0
	occ = occurrences(doc, now, now + timedelta(days=HORIZON_DAYS))
	starts = {o[0] for o in occ}
	for r in kept:  # the meeting moved: a pop-up for the old time is no longer true
		if r.status == "Due" and get_datetime(r.occurrence_start) not in starts:
			frappe.db.set_value(REMINDER, r.name, "status", "Cancelled", update_modified=False)
	done = {(r.user, get_datetime(r.occurrence_start), r.remind_before) for r in kept if r.status != "Cancelled"}
	touched = {(r.user, get_datetime(r.occurrence_start)) for r in kept if r.status != "Cancelled"}
	rules = [r for r in (doc.get("reminders") or []) if cint(r.popup) or cint(r.email)]
	people = recipients(doc)
	created = 0
	for start, end in occ:
		if start <= now:
			continue  # already started: nothing to remind about
		late = {"popup": 0, "email": 0}
		for rule in rules:
			at = start - timedelta(minutes=OFFSETS.get(rule.remind_before, 15))
			if at <= now:
				late["popup"] |= cint(rule.popup)
				late["email"] |= cint(rule.email)
				continue
			for user in people:
				if (user, start, rule.remind_before) in done:
					continue
				_queue(doc, user, start, end, at, rule.remind_before, rule.popup, rule.email)
				created += 1
		if late["popup"] or late["email"]:
			# scheduled (or moved) inside a reminder window: remind once, now
			for user in people:
				if (user, start) in touched:
					continue
				_queue(doc, user, start, end, now, LATE_RULE, late["popup"], late["email"])
				created += 1
	return created


def _queue(doc, user, start, end, at, rule, popup, email):
	frappe.get_doc({"doctype": REMINDER, "schedule": doc.name, "subject": doc.subject, "user": user,
		"status": "Pending", "occurrence_start": start, "occurrence_end": end, "remind_at": at,
		"remind_before": rule, "popup": cint(popup), "email": cint(email)}).insert(ignore_permissions=True)


def extend_reminders():
	"""Daily: queue the next HORIZON_DAYS of every live repeating schedule; expire stale reminders."""
	now = now_datetime()
	for name in frappe.get_all(SCHEDULE, filters={"status": "Scheduled", "repeat": ["!=", NO_REPEAT]}, pluck="name"):
		try:
			doc = frappe.get_doc(SCHEDULE, name)
			if doc.repeat_until and getdate(doc.repeat_until) < now.date():
				continue
			rebuild_reminders(doc, now)
			push_next_date(doc)
		except Exception:
			log_error("follow-up schedule extend")
	frappe.db.sql(f"""update `tab{REMINDER}` set status='Expired'
		where status in ('Pending','Due') and occurrence_end < %s""", (now - timedelta(hours=1),))


def run_due_reminders():
	"""Every minute: send what is due. Email once; pop-up stays Due until dismissed or snoozed."""
	now = now_datetime()
	rows = frappe.get_all(REMINDER, filters={"status": "Pending", "remind_at": ["<=", now]},
		fields=["name", "schedule", "user", "occurrence_start", "occurrence_end", "remind_before", "popup", "email",
			"email_sent"], order_by="remind_at asc", limit_page_length=500)
	cache = {}
	for r in rows:
		try:
			if r.occurrence_end and get_datetime(r.occurrence_end) < now:
				frappe.db.set_value(REMINDER, r.name, "status", "Expired", update_modified=False)
				continue
			if r.schedule not in cache:
				cache[r.schedule] = frappe.get_doc(SCHEDULE, r.schedule) if frappe.db.exists(SCHEDULE, r.schedule) else None
			sched = cache[r.schedule]
			if not sched or sched.status != "Scheduled":
				frappe.db.set_value(REMINDER, r.name, "status", "Cancelled", update_modified=False)
				continue
			values = {"status": "Due" if cint(r.popup) else "Done"}
			if cint(r.email) and not cint(r.email_sent):
				send_reminder_email(sched, r)
				values["email_sent"] = 1
			if cint(r.popup):
				push_popup(sched, r)
			frappe.db.set_value(REMINDER, r.name, values, update_modified=False)
		except Exception:
			log_error("follow-up reminder")
	if rows:
		frappe.db.commit()


# ============================================================================ what a reminder shows
def reference_title(doctype, name):
	if not doctype or not name or not frappe.db.exists(doctype, name):
		return name or ""
	meta = frappe.get_meta(doctype)
	fields = [f for f in ((meta.title_field,) + TITLE_FIELDS) if f and meta.has_field(f)]
	if fields:
		row = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
		for f in fields:
			if row.get(f):
				return row[f]
	return name


def _when(start, end, all_day=False):
	start, end = get_datetime(start), get_datetime(end)
	if all_day:
		return format_datetime(start, "EEE dd MMM yyyy") + " · " + _("All day")
	same = start.date() == end.date()
	return f"{format_datetime(start, 'EEE dd MMM yyyy, h:mm a')} – {format_datetime(end, 'h:mm a' if same else 'EEE dd MMM, h:mm a')}"


def attachments(name):
	return frappe.get_all("File", filters={"attached_to_doctype": SCHEDULE, "attached_to_name": name},
		fields=["name", "file_name", "file_url", "is_private"], order_by="creation asc")


def payload(sched, r):
	start, end = get_datetime(r.occurrence_start), get_datetime(r.occurrence_end)
	minutes = math.ceil((start - now_datetime()).total_seconds() / 60)
	return {
		"name": r.name, "schedule": sched.name, "subject": sched.subject, "platform": sched.platform,
		"meeting_link": sched.meeting_link or "", "location": sched.location or "",
		"start": str(start), "end": str(end), "when": _when(start, end, cint(sched.all_day)), "starts_in": minutes,
		"reference_doctype": sched.reference_doctype, "reference_name": sched.reference_name,
		"reference_title": reference_title(sched.reference_doctype, sched.reference_name),
		"lead_owner": frappe.utils.get_fullname(sched.lead_owner) if sched.lead_owner else "",
		"organizer": frappe.utils.get_fullname(sched.organizer) if sched.organizer else "",
		"agenda": strip_html(sched.agenda or "")[:300], "recurring": sched.repeat != NO_REPEAT,
		"attachments": [{"file_name": f.file_name, "file_url": f.file_url} for f in attachments(sched.name)],
		"rule": r.remind_before,
	}


def push_popup(sched, r):
	data = payload(sched, r)
	frappe.publish_realtime("alphax_followup_reminder", data, user=r.user, after_commit=True)
	try:
		frappe.get_doc({"doctype": "Notification Log", "for_user": r.user, "type": "Alert",
			"subject": _("Reminder: {0} · {1}").format(escape_html(sched.subject), data["when"]),
			"document_type": SCHEDULE, "document_name": sched.name, "from_user": sched.organizer,
		}).insert(ignore_permissions=True)
	except Exception:
		log_error("follow-up reminder bell")


def _card(sched, start, end, internal=True):
	rows = [(_("When"), escape_html(_when(start, end, cint(sched.all_day))))]
	rows.append((_("Platform"), escape_html(_(sched.platform or ""))))
	if sched.meeting_link:
		link = escape_html(sched.meeting_link)
		rows.append((_("Join"), f'<a href="{link}" style="background:#5b5fc7;color:#fff;padding:6px 14px;border-radius:4px;'
			f'text-decoration:none;display:inline-block">{_("Join meeting")}</a><br><span style="font-size:11px;color:#6b7280">{link}</span>'))
	if sched.location:
		rows.append((_("Location"), escape_html(sched.location)))
	if internal:
		rows.append((_("Regarding"), escape_html(f"{_(sched.reference_doctype)} {sched.reference_name} · "
			f"{reference_title(sched.reference_doctype, sched.reference_name)}")))
	people = [escape_html(a.full_name or a.email or a.user) for a in (sched.get("attendees") or [])]
	if people:
		rows.append((_("Attendees"), ", ".join(people)))
	body = "".join(f'<tr><td style="padding:4px 12px 4px 0;color:#6b7280;vertical-align:top;white-space:nowrap">{k}</td>'
		f'<td style="padding:4px 0">{v}</td></tr>' for k, v in rows)
	agenda = f'<div style="margin-top:12px">{sched.agenda}</div>' if sched.agenda else ""
	return f'<table style="border-collapse:collapse;font-size:14px">{body}</table>{agenda}'


def send_reminder_email(sched, r):
	email = frappe.db.get_value("User", r.user, "email")
	if not email:
		return
	from alphax_crm.crm.emails import with_document_footer

	start, end = get_datetime(r.occurrence_start), get_datetime(r.occurrence_end)
	head = (_("Starting soon") if r.remind_before == LATE_RULE else _(r.remind_before or "")).strip()
	html = f'<p style="font-size:15px"><b>{escape_html(sched.subject)}</b> — {escape_html(head)}</p>' + _card(sched, start, end)
	html += f'<p><a href="{get_url_to_form(SCHEDULE, sched.name)}">{_("Open the meeting in the ERP")}</a></p>'
	html = with_document_footer(html, _lead(sched), sched.reference_doctype, sched.reference_name)
	frappe.sendmail(recipients=[email], subject=_("Reminder: {0} — {1}").format(sched.subject, _when(start, end, cint(sched.all_day))),
		message=html, reference_doctype=SCHEDULE, reference_name=sched.name, now=True)


def _lead(sched):
	from alphax_crm.crm.automation import lead_of

	try:
		return lead_of(sched.reference_doctype, sched.reference_name)
	except Exception:
		return None


# ============================================================================ pop-up actions (desk)
def _own(name):
	row = frappe.db.get_value(REMINDER, name, ["name", "user", "schedule", "occurrence_start", "status"], as_dict=True)
	if not row or row.user != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return row


@frappe.whitelist()
def my_due_reminders():
	"""Pop-ups still open for the current user (shown when the desk loads)."""
	now = now_datetime()
	rows = frappe.get_all(REMINDER, filters={"user": frappe.session.user, "status": "Due", "popup": 1,
		"occurrence_end": [">=", now - timedelta(minutes=30)]},
		fields=["name", "schedule", "user", "occurrence_start", "occurrence_end", "remind_before"],
		order_by="occurrence_start asc", limit_page_length=20)
	out, seen = [], set()
	for r in rows:
		key = (r.schedule, str(r.occurrence_start))
		if key in seen or not frappe.db.exists(SCHEDULE, r.schedule):
			continue
		seen.add(key)
		out.append(payload(frappe.get_doc(SCHEDULE, r.schedule), r))
	return out


def _close_siblings(row, status):
	frappe.db.sql(f"""update `tab{REMINDER}` set status=%s where user=%s and schedule=%s and occurrence_start=%s
		and status='Due'""", (status, row.user, row.schedule, row.occurrence_start))


@frappe.whitelist()
def dismiss_reminder(name):
	row = _own(name)
	_close_siblings(row, "Dismissed")
	frappe.db.set_value(REMINDER, name, "status", "Dismissed", update_modified=False)
	return True


@frappe.whitelist()
def snooze_reminder(name, minutes=5):
	row = _own(name)
	minutes = cint(minutes)
	if minutes not in SNOOZE_MINUTES:
		minutes = 5
	_close_siblings(row, "Dismissed")
	frappe.db.set_value(REMINDER, name, {"status": "Pending", "remind_at": now_datetime() + timedelta(minutes=minutes),
		"snoozed": cint(frappe.db.get_value(REMINDER, name, "snoozed")) + 1, "email_sent": 1}, update_modified=False)
	return True


# ============================================================================ calendar Event
def sync_event(doc):
	"""One Frappe Event per schedule: calendar + the record's Activities tab."""
	meta = frappe.get_meta("Event")
	event = frappe.get_doc("Event", doc.event) if doc.event and frappe.db.exists("Event", doc.event) else None
	if not event:
		if doc.status == "Cancelled":
			return
		event = frappe.new_doc("Event")
	values = {
		"subject": f"{doc.subject} · {reference_title(doc.reference_doctype, doc.reference_name)}",
		"event_category": "Meeting", "event_type": "Private", "send_reminder": 0,
		"starts_on": doc.start_datetime, "ends_on": doc.end_datetime, "all_day": cint(doc.all_day),
		"status": {"Scheduled": "Open", "Completed": "Completed", "Cancelled": "Cancelled"}.get(doc.status, "Open"),
		"description": _event_description(doc), "location": doc.location or doc.meeting_link or "",
	}
	every = cint(doc.repeat_every) or 1
	values["repeat_this_event"] = 0
	if doc.repeat == WORKING:
		from alphax_crm.crm import automation as auto

		days = auto.calendar().days
		values.update(repeat_this_event=1, repeat_on="Weekly", repeat_till=doc.repeat_until)
		for i, day in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")):
			values[day] = 1 if i in days else 0
	elif doc.repeat in ("Daily", "Weekly", "Monthly") and every == 1:  # Event has no "every N"
		values.update(repeat_this_event=1, repeat_on=doc.repeat, repeat_till=doc.repeat_until)
		if doc.repeat == "Weekly":
			for i, day in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")):
				values[day] = 1 if i == get_datetime(doc.start_datetime).weekday() else 0
	for k, v in values.items():
		if meta.has_field(k):
			event.set(k, v)
	if meta.has_field("event_participants") and not any(
			p.reference_doctype == doc.reference_doctype and p.reference_docname == doc.reference_name
			for p in event.get("event_participants") or []):
		event.append("event_participants", {"reference_doctype": doc.reference_doctype, "reference_docname": doc.reference_name})
	event.flags.ignore_permissions = True
	if event.is_new():
		event.owner = doc.organizer or frappe.session.user
		event.insert()
		doc.db_set("event", event.name, update_modified=False)
	else:
		event.save()


def _event_description(doc):
	parts = [f"<b>{escape_html(_(doc.platform or ''))}</b>"]
	if doc.meeting_link:
		parts.append(f'<a href="{escape_html(doc.meeting_link)}">{_("Join meeting")}</a>')
	parts.append(f'<a href="{get_url_to_form(SCHEDULE, doc.name)}">{_("Open follow-up schedule")}</a>')
	return " · ".join(parts) + (f"<br>{doc.agenda}" if doc.agenda else "")


@frappe.whitelist()
def get_calendar_events(start, end, filters=None):
	"""Calendar view: every occurrence of each schedule in the visible range, not just the first."""
	conditions = [["status", "!=", "Cancelled"], ["start_datetime", "<=", end]]
	if filters:
		filters = frappe.parse_json(filters)
		if isinstance(filters, dict):
			conditions += [[k, "=", v] for k, v in filters.items() if v not in (None, "")]
		elif isinstance(filters, list):
			conditions += [f[1:] if len(f) == 4 else f for f in filters if isinstance(f, (list, tuple))]
	out = []
	for s in frappe.get_list(SCHEDULE, filters=conditions, fields=["name", "subject", "status", "platform", "all_day",
			"start_datetime", "end_datetime", "repeat", "repeat_every", "repeat_until", "reference_name"], limit_page_length=1000):
		for i, (a, b) in enumerate(occurrences(s, start, end)):
			out.append({"name": s.name, "id": f"{s.name}::{i}", "subject": f"{s.subject} ({s.reference_name})",
				"start_datetime": a, "end_datetime": b, "all_day": cint(s.all_day), "status": s.status,
				"color": "#5b5fc7" if s.status == "Scheduled" else "#10b981"})
	return out


# ============================================================================ invitations (.ics)
def _ics_escape(text):
	return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line):
	raw = line.encode("utf-8")
	if len(raw) <= 75:
		return line
	parts, cur = [], b""
	for ch in line:
		b = ch.encode("utf-8")
		if len(cur) + len(b) > (75 if not parts else 74):
			parts.append(cur.decode("utf-8"))
			cur = b""
		cur += b
	parts.append(cur.decode("utf-8"))
	return "\r\n ".join(parts)


def _utc(dt):
	return convert(dt, system_tz(), "UTC").strftime("%Y%m%dT%H%M%SZ")


def rrule(doc):
	repeat = doc.get("repeat") or NO_REPEAT
	if repeat == NO_REPEAT:
		return None
	every = max(1, cint(doc.get("repeat_every")) or 1)
	if repeat == WORKING:
		from alphax_crm.crm import automation as auto

		rule = "FREQ=WEEKLY;BYDAY=" + ",".join(ICS_DAYS[d] for d in sorted(auto.calendar().days))
	else:
		rule = {"Daily": "FREQ=DAILY", "Weekly": "FREQ=WEEKLY", "Monthly": "FREQ=MONTHLY"}[repeat] + (f";INTERVAL={every}" if every > 1 else "")
	if doc.get("repeat_until"):
		rule += ";UNTIL=" + _utc(datetime.combine(getdate(doc.repeat_until), time(23, 59, 59)))
	return rule


def build_ics(doc, method="REQUEST", internal=True):
	host = (get_url() or "alphax").split("//")[-1].split("/")[0]
	organizer = doc.organizer or frappe.session.user
	org_email = frappe.db.get_value("User", organizer, "email") or organizer
	desc = strip_html(doc.agenda or "")
	if doc.meeting_link:
		desc = f"{_('Join')}: {doc.meeting_link}\n\n{desc}"
	if internal:
		desc += f"\n\n{_('Open in ERP')}: {get_url_to_form(SCHEDULE, doc.name)}"
	lines = ["BEGIN:VCALENDAR", "PRODID:-//AlphaX CRM//Follow-up Schedule//EN", "VERSION:2.0", "CALSCALE:GREGORIAN",
		f"METHOD:{method}", "BEGIN:VEVENT", f"UID:{doc.name}@{host}",
		f"SEQUENCE:{int(now_datetime().timestamp() // 60) % 2147483647}", f"DTSTAMP:{_utc(now_datetime())}"]
	if cint(doc.all_day):
		s, e = getdate(doc.start_datetime), getdate(doc.end_datetime) + timedelta(days=1)
		lines += [f"DTSTART;VALUE=DATE:{s.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{e.strftime('%Y%m%d')}"]
	else:
		lines += [f"DTSTART:{_utc(doc.start_datetime)}", f"DTEND:{_utc(doc.end_datetime)}"]
	rule = rrule(doc)
	if rule:
		lines.append(f"RRULE:{rule}")
	lines += [f"SUMMARY:{_ics_escape(doc.subject)}", f"DESCRIPTION:{_ics_escape(desc)}",
		f"LOCATION:{_ics_escape(doc.location or doc.meeting_link or _(doc.platform or ''))}",
		f"ORGANIZER;CN={_ics_escape(frappe.utils.get_fullname(organizer))}:mailto:{org_email}",
		f"STATUS:{'CANCELLED' if method == 'CANCEL' else 'CONFIRMED'}"]
	if doc.meeting_link:
		lines.append(f"URL:{doc.meeting_link}")
	for a in doc.get("attendees") or []:
		if not a.email:
			continue
		role = "OPT-PARTICIPANT" if a.attendance == "Optional" else "REQ-PARTICIPANT"
		lines.append(f"ATTENDEE;CN={_ics_escape(a.full_name or a.email)};ROLE={role};PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{a.email}")
	first = sorted(OFFSETS.get(r.remind_before, 15) for r in (doc.get("reminders") or []) if cint(r.get("popup")) or cint(r.get("email")))
	if first and method != "CANCEL":
		lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(doc.subject)}",
			f"TRIGGER:-PT{first[0]}M", "END:VALARM"]
	lines += ["END:VEVENT", "END:VCALENDAR"]
	return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def send_invitation(doc, method="REQUEST"):
	"""Calendar invitation with the attachments. Internal attendees: ERP link + Lead Owner. External: clean."""
	internal = [a.email for a in doc.get("attendees") or [] if a.email and a.attendee_type == "Internal"]
	external = [a.email for a in doc.get("attendees") or [] if a.email and a.attendee_type == "External"]
	if not internal and not external:
		return
	from alphax_crm.crm.emails import with_document_footer

	reply_to = frappe.db.get_value("User", doc.organizer, "email") if doc.organizer else None
	files = [{"fid": f.name} for f in attachments(doc.name)]
	cancel = method == "CANCEL"
	subject = (_("Cancelled: {0}") if cancel else _("Invitation: {0}")).format(doc.subject) + \
		f" — {_when(doc.start_datetime, doc.end_datetime, cint(doc.all_day))}"
	intro = _("This meeting has been cancelled.") if cancel else _("You are invited to the meeting below.")
	for group, is_internal in ((internal, True), (external, False)):
		if not group:
			continue
		html = f"<p>{intro}</p>" + _card(doc, doc.start_datetime, doc.end_datetime, internal=is_internal)
		if is_internal:
			html = with_document_footer(html, _lead(doc), doc.reference_doctype, doc.reference_name)
		ics = build_ics(doc, method=method, internal=is_internal)
		frappe.sendmail(recipients=group, subject=subject, message=html, reply_to=reply_to,
			reference_doctype=SCHEDULE, reference_name=doc.name,
			attachments=[{"fname": "invite.ics", "fcontent": ics.encode("utf-8")}] + ([] if cancel else files))
	doc.db_set("invitation_sent_on", now_datetime(), update_modified=False)


# ============================================================================ the Schedule Follow-up screen
def _reference_email(doctype, name):
	meta = frappe.get_meta(doctype)
	fields = [f for f in EMAIL_FIELDS if meta.has_field(f)]
	if not fields:
		return None
	row = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
	return next((row[f] for f in fields if row.get(f)), None)


@frappe.whitelist()
def get_schedule_context(reference_doctype=None, reference_name=None, name=None):
	settings = get_settings()
	doc = None
	if name:
		doc = frappe.get_doc(SCHEDULE, name)
		doc.check_permission("read")
		reference_doctype, reference_name = doc.reference_doctype, doc.reference_name
	if reference_doctype and reference_name:
		frappe.get_doc(reference_doctype, reference_name).check_permission("read")
	from alphax_crm.crm.automation import lead_owner_of

	owner = lead_owner_of(reference_doctype, reference_name) if reference_name else None
	ctx = {
		"system_tz": system_tz(),
		"defaults": {"platform": settings.get("schedule_default_platform") or "Microsoft Teams",
			"duration": default_duration(settings), "reminders": default_rules(settings),
			"send_invitation": _flag(settings, "schedule_invite_by_default", 0)},
		"reminder_options": list(OFFSETS), "snooze": SNOOZE_MINUTES,
		"connections": _connections(),
		"can_setup_connections": "System Manager" in frappe.get_roles(),
		"reference": {"doctype": reference_doctype, "name": reference_name,
			"title": reference_title(reference_doctype, reference_name) if reference_name else "",
			"email": _reference_email(reference_doctype, reference_name) if reference_name else None,
			"lead_owner": owner, "lead_owner_name": frappe.utils.get_fullname(owner) if owner else ""},
		"doc": None, "attachments": [],
	}
	if doc:
		tz = _valid_tz(doc.time_zone) or ctx["system_tz"]
		d = doc.as_dict(no_default_fields=True)
		d["start_local"] = str(convert(doc.start_datetime, ctx["system_tz"], tz))
		d["end_local"] = str(convert(doc.end_datetime, ctx["system_tz"], tz))
		d["display_tz"] = tz
		d["can_write"] = frappe.has_permission(SCHEDULE, "write", doc)
		ctx["doc"] = d
		ctx["attachments"] = attachments(doc.name)
	return ctx


def _connections():
	try:
		from alphax_crm.crm.meeting_connect import status_for_ui

		return status_for_ui()
	except Exception:
		log_error("meeting connections")
		return {}


@frappe.whitelist()
def save_schedule(data):
	"""Create or update a schedule from the Schedule Follow-up screen. Times arrive in data.time_zone."""
	data = frappe._dict(frappe.parse_json(data))
	if data.name:
		doc = frappe.get_doc(SCHEDULE, data.name)
		doc.check_permission("write")
	else:
		frappe.get_doc(data.reference_doctype, data.reference_name).check_permission("read")
		doc = frappe.new_doc(SCHEDULE)
		doc.reference_doctype, doc.reference_name = data.reference_doctype, data.reference_name
		doc.source_follow_up = data.source_follow_up or None
	tz = _valid_tz(data.time_zone) or system_tz()
	doc.time_zone = tz
	doc.subject = (data.subject or "").strip() or _("Follow-up with {0}").format(
		reference_title(doc.reference_doctype, doc.reference_name))
	doc.platform = data.platform
	doc.all_day = cint(data.all_day)
	if doc.all_day:  # a day is a day: no shifting across zones
		doc.start_datetime, doc.end_datetime = get_datetime(data.start), get_datetime(data.end) if data.end else None
	else:
		doc.start_datetime = convert(data.start, tz, system_tz())
		doc.end_datetime = convert(data.end, tz, system_tz()) if data.end else None
	doc.repeat = data.repeat or NO_REPEAT
	doc.repeat_every = cint(data.repeat_every) or 1
	doc.repeat_until = data.repeat_until or None
	doc.meeting_link = (data.meeting_link or "").strip()
	doc.location = (data.location or "").strip()
	doc.agenda = data.agenda or ""
	doc.send_invitation = cint(data.send_invitation)
	if data.get("create_online_meeting") is not None:
		doc.create_online_meeting = cint(data.create_online_meeting)
	elif doc.is_new():
		from alphax_crm.crm.meeting_connect import connection

		conn = connection(data.platform)
		doc.create_online_meeting = cint(conn.auto_create) if conn else 0
	if data.organizer:
		doc.organizer = data.organizer
	doc.set("attendees", [])
	for user in data.internal or []:
		u = user.get("user") if isinstance(user, dict) else user
		if u:
			doc.append("attendees", {"attendee_type": "Internal", "user": u,
				"attendance": (user.get("attendance") if isinstance(user, dict) else None) or "Required"})
	for email in data.external or []:
		e = (email.get("email") if isinstance(email, dict) else email or "").strip()
		if e:
			if not frappe.utils.validate_email_address(e):
				frappe.throw(_("{0} is not a valid email address.").format(escape_html(e)))
			doc.append("attendees", {"attendee_type": "External", "email": e,
				"attendance": (email.get("attendance") if isinstance(email, dict) else None) or "Required"})
	doc.set("reminders", [])
	for r in data.reminders or []:
		if r.get("remind_before") in OFFSETS and (cint(r.get("popup")) or cint(r.get("email"))):
			doc.append("reminders", {"remind_before": r["remind_before"], "popup": cint(r.get("popup")), "email": cint(r.get("email"))})
	if not doc.reminders:
		doc.append("reminders", {"remind_before": "15 minutes before", "popup": 0, "email": 0})  # "no reminders"
	if data.status in ("Scheduled", "Cancelled"):
		doc.status = data.status
	doc.save()
	return {"name": doc.name, "invitation_sent_on": doc.invitation_sent_on}


@frappe.whitelist()
def cancel_schedule(name):
	doc = frappe.get_doc(SCHEDULE, name)
	doc.check_permission("write")
	doc.status = "Cancelled"
	doc.save()
	return doc.name


def link_logged_followup(schedule, followup):
	"""Log Follow-up opened from a meeting: link both ways. A one-off meeting is then Completed; a repeating
	series stays Scheduled (only that occurrence is logged)."""
	if not schedule or not frappe.db.exists(SCHEDULE, schedule):
		return
	doc = frappe.get_doc(SCHEDULE, schedule)
	doc.completed_follow_up = followup
	if doc.repeat == NO_REPEAT and doc.status == "Scheduled":
		doc.status = "Completed"
		doc.completed_on = now_datetime()
	doc.flags.ignore_permissions = True
	doc.save()
