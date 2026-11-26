"""Meeting connections: create the real Teams / Zoom / Google Meet / Webex meeting from a scheduled follow-up (0.51.0).

Setup lives in *AlphaX Meeting Connection* (one record per platform, System Manager only). When a follow-up via a
connected platform is saved with "Create the online meeting automatically" ticked, AlphaX:

* creates the meeting on the platform (hosted by the organizer's own account when they have one, else the default
  host), stores its id and join link on the follow-up, and puts the link in reminders, the Lead's panel, the
  calendar Event and the invitation;
* updates it when the time, title, link details or repeat change;
* cancels it when the follow-up is cancelled, the platform changes, or the tick is removed.

Microsoft Teams  Microsoft Graph, app-only: POST /users/{host}/events with isOnlineMeeting (teamsForBusiness).
                 The event sits in the host's Outlook calendar; Outlook can send the invitations.
Zoom             Server-to-Server OAuth app: POST /users/{host}/meetings.
Google Meet      Service account with domain-wide delegation: Calendar events.insert with a Meet conference.
Webex            Meetings API with an access token (optionally renewed with a refresh token).

A failure never stops the follow-up from saving: the problem is shown to the user and kept on the follow-up
(online_meeting_error), and the Health Check reports it.
"""

from __future__ import annotations

import json
import time as _time
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime, strip_html

CONNECTION = "AlphaX Meeting Connection"
PLATFORMS = ("Microsoft Teams", "Zoom", "Google Meet", "Webex")
TIMEOUT = 20
GRAPH = "https://graph.microsoft.com/v1.0"
ZOOM = "https://api.zoom.us/v2"
GCAL = "https://www.googleapis.com/calendar/v3"
WEBEX = "https://webexapis.com/v1"
GRAPH_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class MeetingError(Exception):
	pass


# ============================================================================ connections
def connection(platform):
	if platform not in PLATFORMS or not frappe.db.exists(CONNECTION, platform):
		return None
	conn = frappe.get_doc(CONNECTION, platform)
	return conn if cint(conn.enabled) else None


def status_for_ui():
	"""{platform: {...}} for the scheduler: which platforms can create meetings, and how."""
	out = {}
	if not frappe.db.exists("DocType", CONNECTION):
		return out
	for c in frappe.get_all(CONNECTION, fields=["platform", "enabled", "auto_create", "provider_sends_invites"]):
		out[c.platform] = {"enabled": cint(c.enabled), "auto_create": cint(c.auto_create),
			"sends_invites": cint(c.provider_sends_invites) and c.platform != "Zoom"}
	return out


def validate_connection(conn):
	conn.host_email = (conn.host_email or "").strip().lower()
	if conn.platform == "Google Meet" and conn.google_key_file and not conn.google_key_file.startswith("/private/"):
		frappe.throw(_("Attach the service account key as a private file (tick Private when uploading)."))


def _secret(conn, field):
	try:
		return conn.get_password(field, raise_exception=False) or ""
	except Exception:
		return ""


def _cache_get(key):
	return frappe.cache().get_value(f"alphax_meet:{key}")


def _cache_set(key, value, seconds):
	frappe.cache().set_value(f"alphax_meet:{key}", value, expires_in_sec=max(60, int(seconds) - 120))


# ============================================================================ http
def _http(method, url, token=None, expected=(200, 201, 202, 204), **kw):
	import requests

	headers = {"Accept": "application/json"}
	if token:
		headers["Authorization"] = f"Bearer {token}"
	headers.update(kw.pop("headers", {}) or {})
	try:
		r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kw)
	except requests.RequestException as e:
		raise MeetingError(_("Could not reach {0}: {1}").format(url.split("/")[2], e))
	if r.status_code not in expected:
		raise MeetingError(_describe(r))
	if not r.content:
		return {}
	try:
		return r.json()
	except ValueError:
		return {}


def _describe(r):
	try:
		body = r.json()
	except ValueError:
		return f"HTTP {r.status_code}: {(r.text or '')[:300]}"
	err = body.get("error")
	if isinstance(err, dict):
		msg = err.get("message") or err.get("code")
	else:
		msg = body.get("error_description") or err or body.get("message") or body
	return f"HTTP {r.status_code}: {str(msg)[:400]}"


# ============================================================================ time helpers
def _utc(dt):
	from alphax_crm.crm.schedule import convert, system_tz

	return convert(get_datetime(dt), system_tz(), "UTC")


def _iso_z(dt):
	return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def _minutes(doc):
	return max(5, int((get_datetime(doc.end_datetime) - get_datetime(doc.start_datetime)).total_seconds() // 60))


def _attendees(doc):
	return [a for a in (doc.get("attendees") or []) if a.get("email")]


def _description(doc, html=True):
	from frappe.utils import get_url_to_form

	from alphax_crm.crm.schedule import SCHEDULE, reference_title

	head = _("Regarding {0} {1} · {2}").format(_(doc.reference_doctype), doc.reference_name,
		reference_title(doc.reference_doctype, doc.reference_name))
	agenda = doc.agenda or ""
	if html:
		return f"<p>{frappe.utils.escape_html(head)}</p>{agenda}"
	return f"{head}\n\n{strip_html(agenda)}\n\n{get_url_to_form(SCHEDULE, doc.name)}"


def _working_days():
	from alphax_crm.crm import automation as auto

	return sorted(auto.calendar().days)


def _data(doc):
	try:
		return json.loads(doc.online_meeting_data or "{}")
	except ValueError:
		return {}


# ============================================================================ Microsoft Teams (Graph)
def _graph_token(conn):
	key = f"graph:{conn.tenant_id}:{conn.client_id}"
	tok = _cache_get(key)
	if tok:
		return tok
	res = _http("POST", f"https://login.microsoftonline.com/{conn.tenant_id}/oauth2/v2.0/token", data={
		"client_id": conn.client_id, "client_secret": _secret(conn, "client_secret"),
		"scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"})
	_cache_set(key, res["access_token"], res.get("expires_in", 3600))
	return res["access_token"]


def _graph_recurrence(doc):
	rep = doc.repeat or "Does not repeat"
	if rep == "Does not repeat":
		return None
	every = max(1, cint(doc.repeat_every) or 1)
	start = _utc(doc.start_datetime)
	if rep == "Daily":
		pattern = {"type": "daily", "interval": every}
	elif rep == "Every working day":
		pattern = {"type": "weekly", "interval": 1, "daysOfWeek": [GRAPH_DAYS[d] for d in _working_days()], "firstDayOfWeek": "sunday"}
	elif rep == "Weekly":
		pattern = {"type": "weekly", "interval": every, "daysOfWeek": [GRAPH_DAYS[start.weekday()]], "firstDayOfWeek": "sunday"}
	else:
		pattern = {"type": "absoluteMonthly", "interval": every, "dayOfMonth": start.day}
	rng = {"type": "endDate", "startDate": start.date().isoformat(), "endDate": getdate(doc.repeat_until).isoformat()} \
		if doc.repeat_until else {"type": "noEnd", "startDate": start.date().isoformat()}
	return {"pattern": pattern, "range": rng}


def _graph_body(conn, doc):
	if cint(doc.all_day):
		s = getdate(doc.start_datetime)
		e = getdate(doc.end_datetime) + timedelta(days=1)
		start = {"dateTime": f"{s.isoformat()}T00:00:00", "timeZone": "UTC"}
		end = {"dateTime": f"{e.isoformat()}T00:00:00", "timeZone": "UTC"}
	else:
		start = {"dateTime": _utc(doc.start_datetime).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}
		end = {"dateTime": _utc(doc.end_datetime).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}
	body = {"subject": doc.subject, "body": {"contentType": "HTML", "content": _description(doc)},
		"start": start, "end": end, "isAllDay": bool(cint(doc.all_day)),
		"location": {"displayName": doc.location or "Microsoft Teams Meeting"}, "allowNewTimeProposals": True}
	if cint(conn.provider_sends_invites):
		body["attendees"] = [{"emailAddress": {"address": a.email, "name": a.full_name or a.email},
			"type": "optional" if a.attendance == "Optional" else "required"} for a in _attendees(doc)]
	rec = _graph_recurrence(doc)
	body["recurrence"] = rec
	return body


def _graph_host_ok(token, user):
	try:
		_http("GET", f"{GRAPH}/users/{user}?$select=id", token)
		return True
	except MeetingError:
		return False


def teams_create(conn, doc):
	token = _graph_token(conn)
	host = _pick_host(conn, doc, lambda u: _graph_host_ok(token, u))
	body = _graph_body(conn, doc)
	if not body.get("recurrence"):
		body.pop("recurrence", None)
	body.update({"isOnlineMeeting": True, "onlineMeetingProvider": "teamsForBusiness", "transactionId": f"{doc.name}-{int(_time.time())}"})
	ev = _http("POST", f"{GRAPH}/users/{host}/events", token, json=body)
	join = (ev.get("onlineMeeting") or {}).get("joinUrl")
	if not join:  # Teams sometimes fills the link a moment later
		_time.sleep(2)
		ev = _http("GET", f"{GRAPH}/users/{host}/events/{ev['id']}?$select=onlineMeeting,webLink", token)
		join = (ev.get("onlineMeeting") or {}).get("joinUrl")
	return ev["id"], join, host, {}


def teams_update(conn, doc):
	token = _graph_token(conn)
	body = _graph_body(conn, doc)
	_http("PATCH", f"{GRAPH}/users/{doc.online_meeting_host}/events/{doc.online_meeting_id}", token, json=body)


def teams_cancel(conn, doc):
	token = _graph_token(conn)
	url = f"{GRAPH}/users/{doc.online_meeting_host}/events/{doc.online_meeting_id}"
	try:
		_http("POST", f"{url}/cancel", token, json={"comment": _("This follow-up has been cancelled.")})
	except MeetingError:
		_http("DELETE", url, token, expected=(204, 404))


def teams_test(conn):
	token = _graph_token(conn)
	_http("GET", f"{GRAPH}/users/{conn.host_email}?$select=id,displayName", token)
	return _("Connected to Microsoft 365; default host {0} found.").format(conn.host_email)


# ============================================================================ Zoom
def _zoom_token(conn):
	key = f"zoom:{conn.zoom_account_id}:{conn.client_id}"
	tok = _cache_get(key)
	if tok:
		return tok
	res = _http("POST", f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={conn.zoom_account_id}",
		auth=(conn.client_id, _secret(conn, "client_secret")))
	_cache_set(key, res["access_token"], res.get("expires_in", 3600))
	return res["access_token"]


def _zoom_body(doc):
	from alphax_crm.crm.schedule import system_tz

	body = {"topic": doc.subject[:200], "agenda": strip_html(_description(doc, html=False))[:1900],
		"start_time": _iso_z(doc.start_datetime), "duration": _minutes(doc), "timezone": system_tz(),
		"type": 2, "settings": {"join_before_host": False, "waiting_room": True}}
	rep = doc.repeat or "Does not repeat"
	if rep != "Does not repeat":
		every = max(1, cint(doc.repeat_every) or 1)
		start = get_datetime(doc.start_datetime)
		zoom_day = lambda wd: str((wd + 1) % 7 + 1)  # noqa: E731  Zoom: 1 = Sunday … 7 = Saturday
		if rep == "Daily":
			rec = {"type": 1, "repeat_interval": every}
		elif rep == "Every working day":
			rec = {"type": 2, "repeat_interval": 1, "weekly_days": ",".join(zoom_day(d) for d in _working_days())}
		elif rep == "Weekly":
			rec = {"type": 2, "repeat_interval": every, "weekly_days": zoom_day(start.weekday())}
		else:
			rec = {"type": 3, "repeat_interval": every, "monthly_day": start.day}
		if doc.repeat_until:
			rec["end_date_time"] = _iso_z(datetime.combine(getdate(doc.repeat_until), datetime.max.time().replace(microsecond=0)))
		else:
			rec["end_times"] = 50
		body.update(type=8, recurrence=rec)
	return body


def zoom_create(conn, doc):
	token = _zoom_token(conn)
	host = _pick_host(conn, doc, lambda u: _zoom_user_ok(token, u))
	m = _http("POST", f"{ZOOM}/users/{host}/meetings", token, json=_zoom_body(doc))
	return str(m["id"]), m.get("join_url"), host, {"start_url_hidden": True}


def _zoom_user_ok(token, user):
	try:
		_http("GET", f"{ZOOM}/users/{user}", token)
		return True
	except MeetingError:
		return False


def zoom_update(conn, doc):
	_http("PATCH", f"{ZOOM}/meetings/{doc.online_meeting_id}", _zoom_token(conn), json=_zoom_body(doc))


def zoom_cancel(conn, doc):
	_http("DELETE", f"{ZOOM}/meetings/{doc.online_meeting_id}?schedule_for_reminder=true", _zoom_token(conn), expected=(204, 404))


def zoom_test(conn):
	_http("GET", f"{ZOOM}/users/{conn.host_email}", _zoom_token(conn))
	return _("Connected to Zoom; default host {0} found.").format(conn.host_email)


# ============================================================================ Google Meet
def _google_key(conn):
	if not conn.google_key_file:
		raise MeetingError(_("Attach the service account key."))
	f = frappe.get_doc("File", {"file_url": conn.google_key_file})
	try:
		return json.loads(f.get_content())
	except (ValueError, TypeError):
		raise MeetingError(_("The service account key is not valid JSON."))


def _google_token(conn, subject):
	key = f"google:{conn.name}:{subject}"
	tok = _cache_get(key)
	if tok:
		return tok
	try:
		import jwt
	except ImportError:
		raise MeetingError(_("PyJWT is not installed on this site."))
	sa = _google_key(conn)
	now = int(_time.time())
	assertion = jwt.encode({"iss": sa["client_email"], "sub": subject, "scope": "https://www.googleapis.com/auth/calendar",
		"aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600}, sa["private_key"], algorithm="RS256")
	res = _http("POST", "https://oauth2.googleapis.com/token",
		data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
	_cache_set(key, res["access_token"], res.get("expires_in", 3600))
	return res["access_token"]


def _google_body(conn, doc):
	from alphax_crm.crm.schedule import rrule

	if cint(doc.all_day):
		start = {"date": getdate(doc.start_datetime).isoformat()}
		end = {"date": (getdate(doc.end_datetime) + timedelta(days=1)).isoformat()}
	else:
		start, end = {"dateTime": _iso_z(doc.start_datetime)}, {"dateTime": _iso_z(doc.end_datetime)}
	body = {"summary": doc.subject, "description": _description(doc), "start": start, "end": end,
		"location": doc.location or "", "reminders": {"useDefault": True}}
	if cint(conn.provider_sends_invites):
		body["attendees"] = [{"email": a.email, "displayName": a.full_name or a.email, "optional": a.attendance == "Optional"}
			for a in _attendees(doc)]
	rule = rrule(doc)
	body["recurrence"] = [f"RRULE:{rule}"] if rule else []
	return body


def _send_updates(conn):
	return "all" if cint(conn.provider_sends_invites) else "none"


def google_create(conn, doc):
	host = _pick_host(conn, doc, lambda u: _google_user_ok(conn, u))
	token = _google_token(conn, host)
	body = _google_body(conn, doc)
	body["conferenceData"] = {"createRequest": {"requestId": f"{doc.name}-{int(_time.time())}",
		"conferenceSolutionKey": {"type": "hangoutsMeet"}}}
	ev = _http("POST", f"{GCAL}/calendars/primary/events?conferenceDataVersion=1&sendUpdates={_send_updates(conn)}", token, json=body)
	join = ev.get("hangoutLink") or next((p.get("uri") for p in (ev.get("conferenceData") or {}).get("entryPoints", [])
		if p.get("entryPointType") == "video"), None)
	return ev["id"], join, host, {}


def _google_user_ok(conn, user):
	try:
		_google_token(conn, user)
		return True
	except MeetingError:
		return False


def google_update(conn, doc):
	token = _google_token(conn, doc.online_meeting_host)
	_http("PATCH", f"{GCAL}/calendars/primary/events/{doc.online_meeting_id}?conferenceDataVersion=1&sendUpdates={_send_updates(conn)}",
		token, json=_google_body(conn, doc))


def google_cancel(conn, doc):
	token = _google_token(conn, doc.online_meeting_host)
	_http("DELETE", f"{GCAL}/calendars/primary/events/{doc.online_meeting_id}?sendUpdates={_send_updates(conn)}",
		token, expected=(200, 204, 404, 410))


def google_test(conn):
	token = _google_token(conn, conn.host_email)
	_http("GET", f"{GCAL}/calendars/primary", token)
	return _("Connected to Google Calendar as {0}.").format(conn.host_email)


# ============================================================================ Webex
def _webex_token(conn, renew=False):
	if not renew:
		tok = _cache_get(f"webex:{conn.name}") or _secret(conn, "webex_access_token")
		if tok:
			return tok
	refresh = _secret(conn, "webex_refresh_token")
	if not (refresh and conn.client_id):
		raise MeetingError(_("The Webex access token was refused and there is no refresh token to renew it."))
	res = _http("POST", f"{WEBEX}/access_token", data={"grant_type": "refresh_token", "client_id": conn.client_id,
		"client_secret": _secret(conn, "client_secret"), "refresh_token": refresh})
	conn.db_set("webex_access_token", res["access_token"])
	if res.get("refresh_token"):
		conn.db_set("webex_refresh_token", res["refresh_token"])
	_cache_set(f"webex:{conn.name}", res["access_token"], res.get("expires_in", 3600))
	return res["access_token"]


def _webex(conn, method, url, **kw):
	try:
		return _http(method, url, _webex_token(conn), **kw)
	except MeetingError as e:
		if "HTTP 401" not in str(e):
			raise
		return _http(method, url, _webex_token(conn, renew=True), **kw)


def _webex_body(conn, doc, host):
	from alphax_crm.crm.schedule import rrule, system_tz

	body = {"title": doc.subject[:128], "agenda": strip_html(_description(doc, html=False))[:1300],
		"start": _iso_z(doc.start_datetime), "end": _iso_z(doc.end_datetime), "timezone": system_tz(),
		"sendEmail": bool(cint(conn.provider_sends_invites)), "enabledAutoRecordMeeting": False}
	if host and host != conn.host_email:
		body["hostEmail"] = host
	rule = rrule(doc)
	if rule:
		body["recurrence"] = rule
	if cint(conn.provider_sends_invites):
		body["invitees"] = [{"email": a.email, "displayName": a.full_name or a.email} for a in _attendees(doc)]
	return body


def webex_create(conn, doc):
	host = (doc.organizer_email or conn.host_email) if cint(conn.use_organizer_account) else conn.host_email
	try:
		m = _webex(conn, "POST", f"{WEBEX}/meetings", json=_webex_body(conn, doc, host))
	except MeetingError:
		if host == conn.host_email:
			raise
		host = conn.host_email  # the token cannot schedule for the organizer: use the default host
		m = _webex(conn, "POST", f"{WEBEX}/meetings", json=_webex_body(conn, doc, host))
	return m["id"], m.get("webLink"), host, {"password": m.get("password")}


def webex_update(conn, doc):
	body = _webex_body(conn, doc, doc.online_meeting_host)
	body["password"] = _data(doc).get("password") or ""
	_webex(conn, "PUT", f"{WEBEX}/meetings/{doc.online_meeting_id}", json=body)


def webex_cancel(conn, doc):
	_webex(conn, "DELETE", f"{WEBEX}/meetings/{doc.online_meeting_id}?sendEmail={'true' if cint(conn.provider_sends_invites) else 'false'}",
		expected=(204, 404))


def webex_test(conn):
	me = _webex(conn, "GET", f"{WEBEX}/people/me")
	return _("Connected to Webex as {0}.").format(", ".join(me.get("emails") or []) or me.get("displayName") or "?")


DRIVERS = {
	"Microsoft Teams": (teams_create, teams_update, teams_cancel, teams_test),
	"Zoom": (zoom_create, zoom_update, zoom_cancel, zoom_test),
	"Google Meet": (google_create, google_update, google_cancel, google_test),
	"Webex": (webex_create, webex_update, webex_cancel, webex_test),
}


def _pick_host(conn, doc, has_account):
	"""The organizer hosts when they have an account on the platform (same email); else the default host."""
	org = (doc.get("organizer_email") or "").lower()
	if cint(conn.use_organizer_account) and org and org != conn.host_email and has_account(org):
		return org
	return conn.host_email


# ============================================================================ keeping a follow-up in step
def sync(doc):
	"""Called after a follow-up schedule is saved. Never raises: problems are stored and shown."""
	if not frappe.db.exists("DocType", CONNECTION):
		return
	doc.organizer_email = frappe.db.get_value("User", doc.organizer, "email") if doc.organizer else None
	had = doc.online_meeting_id and doc.online_meeting_platform
	wants = doc.status == "Scheduled" and cint(doc.create_online_meeting) and doc.platform in PLATFORMS
	error = None
	try:
		if had and (not wants or doc.online_meeting_platform != doc.platform):
			old = connection(doc.online_meeting_platform)
			if old:
				DRIVERS[doc.online_meeting_platform][2](old, doc)
			_store(doc, None, None, None, None, "")  # the old join link no longer works
			had = False
		if not wants:
			return
		conn = connection(doc.platform)
		if not conn:
			raise MeetingError(_("{0} is not connected. Ask a System Manager to set it up in Meeting Connections.").format(_(doc.platform)))
		create, update = DRIVERS[doc.platform][0], DRIVERS[doc.platform][1]
		if not had:
			ext, join, host, extra = create(conn, doc)
			_store(doc, doc.platform, ext, host, extra, join or doc.meeting_link)
			doc.flags.ax_provider_invites = bool(cint(conn.provider_sends_invites) and doc.platform != "Zoom")
		elif doc.flags.get("ax_time_changed") or doc.flags.get("ax_force_meeting_update"):
			update(conn, doc)
			doc.flags.ax_provider_invites = bool(cint(conn.provider_sends_invites) and doc.platform != "Zoom")
	except MeetingError as e:
		error = str(e)
	except Exception as e:  # noqa: BLE001  any driver bug must not stop the save
		frappe.log_error(title="AlphaX CRM: online meeting", message=frappe.get_traceback())
		error = str(e)
	if error:
		doc.db_set("online_meeting_error", f"{now_datetime():%Y-%m-%d %H:%M} · {doc.platform}: {error}"[:1000], update_modified=False)
		frappe.msgprint(_("The {0} meeting could not be created or updated: {1}").format(_(doc.platform), frappe.utils.escape_html(error)),
			title=_("Online meeting"), indicator="orange")
	elif doc.get("online_meeting_error"):
		doc.db_set("online_meeting_error", None, update_modified=False)


def _store(doc, platform, ext, host, extra, link):
	values = {"online_meeting_platform": platform, "online_meeting_id": ext, "online_meeting_host": host,
		"online_meeting_data": json.dumps(extra) if extra else None, "meeting_link": link or ""}
	for k, v in values.items():
		doc.set(k, v)
	doc.db_set(values, update_modified=False)


@frappe.whitelist()
def recreate(name):
	"""Scheduler / form: create the online meeting again (for example after fixing the connection)."""
	from alphax_crm.crm.schedule import SCHEDULE

	doc = frappe.get_doc(SCHEDULE, name)
	doc.check_permission("write")
	if doc.online_meeting_id and doc.online_meeting_platform:
		old = connection(doc.online_meeting_platform)
		try:
			if old:
				DRIVERS[doc.online_meeting_platform][2](old, doc)
		except MeetingError:
			pass
		_store(doc, None, None, None, None, "")
	doc.create_online_meeting = 1
	doc.db_set("create_online_meeting", 1, update_modified=False)
	sync(doc)
	return {"meeting_link": doc.meeting_link, "error": frappe.db.get_value(SCHEDULE, name, "online_meeting_error")}


@frappe.whitelist()
def test_connection(platform):
	frappe.only_for("System Manager")
	conn = frappe.get_doc(CONNECTION, platform)
	try:
		msg, ok = DRIVERS[platform][3](conn), True
	except MeetingError as e:
		msg, ok = str(e), False
	except Exception as e:  # noqa: BLE001
		msg, ok = f"{type(e).__name__}: {e}", False
	conn.db_set({"last_tested_on": now_datetime(), "last_test_result": ("OK · " if ok else "FAILED · ") + msg[:900]})
	return {"ok": ok, "message": msg}


def provider_handles_invites(platform, online_meeting_id):
	"""True when the platform itself sends (and updates / cancels) the invitations for this meeting."""
	if not online_meeting_id or platform not in PLATFORMS or platform == "Zoom":
		return False
	conn = connection(platform)
	return bool(conn and cint(conn.provider_sends_invites))
