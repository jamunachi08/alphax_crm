"""Meeting connections (0.51): request bodies, recurrence, host choice, and create / update / cancel decisions.
No network: the HTTP layer is replaced. python -m unittest tests/test_meeting_connect.py"""
import importlib
import json
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


class D(dict):
	__getattr__ = dict.get

	def __setattr__(self, k, v):
		self[k] = v

	def get(self, k, d=None):
		return dict.get(self, k, d)


class Doc(D):
	def __init__(self, **kw):
		super().__init__(**kw)
		dict.__setitem__(self, "flags", D())
		dict.__setitem__(self, "stored", {})

	def set(self, k, v):
		self[k] = v

	def db_set(self, k, v=None, update_modified=True):
		vals = k if isinstance(k, dict) else {k: v}
		self.stored.update(vals)
		self.update(vals)


def get_datetime(v):
	return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def getdate(v):
	return v if isinstance(v, date) and not isinstance(v, datetime) else get_datetime(v).date()


class MeetingConnectTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
		f = MagicMock()
		f._ = lambda m: m
		u = f.utils
		u.cint.side_effect = lambda v: int(v or 0)
		u.get_datetime.side_effect = get_datetime
		u.getdate.side_effect = getdate
		u.strip_html.side_effect = lambda s: s
		u.escape_html.side_effect = lambda s: s
		u.now_datetime.return_value = datetime(2026, 11, 26, 9, 0)
		u.get_url_to_form.side_effect = lambda dt, n: f"https://erp/app/x/{n}"
		f.db.exists.return_value = True
		f.db.get_value.return_value = "org@irsaa.com"
		cls.f = f
		sched = MagicMock()
		sched.system_tz.return_value = "Asia/Riyadh"
		sched.SCHEDULE = "AlphaX Follow-up Schedule"
		sched.reference_title.return_value = "Samaco"
		from zoneinfo import ZoneInfo

		sched.convert.side_effect = lambda dt, a, b: dt.replace(tzinfo=ZoneInfo(a)).astimezone(ZoneInfo(b)).replace(tzinfo=None)
		sched.rrule.side_effect = lambda d: None if d.get("repeat") in (None, "Does not repeat") else "FREQ=WEEKLY;BYDAY=SU,MO,TU,WE,TH"
		auto = MagicMock()
		auto.calendar.return_value = D(days={6, 0, 1, 2, 3})  # Sunday–Thursday
		cls.mods = patch.dict(sys.modules, {"frappe": f, "frappe.utils": u, "alphax_crm.crm.schedule": sched,
			"alphax_crm.crm.automation": auto})
		cls.mods.start()
		import alphax_crm.crm as pkg

		pkg.schedule, pkg.automation = sched, auto
		cls.m = importlib.import_module("alphax_crm.crm.meeting_connect")

	@classmethod
	def tearDownClass(cls):
		cls.mods.stop()

	def doc(self, **kw):
		base = dict(name="FUS-1", subject="Pricing review", platform="Microsoft Teams", status="Scheduled", organizer="org@irsaa.com",
			start_datetime=datetime(2026, 11, 30, 10, 0), end_datetime=datetime(2026, 11, 30, 10, 45), all_day=0,
			repeat="Does not repeat", repeat_every=1, repeat_until=None, location="", agenda="<p>Agenda</p>",
			reference_doctype="Lead", reference_name="CRM-LEAD-1", create_online_meeting=1, meeting_link="",
			online_meeting_id=None, online_meeting_platform=None, online_meeting_host=None, online_meeting_data=None,
			attendees=[D(email="client@samaco.com", full_name="Zaid", attendance="Required"),
				D(email="opt@x.com", full_name="", attendance="Optional")])
		base.update(kw)
		return Doc(**base)

	def conn(self, **kw):
		base = dict(name="Microsoft Teams", platform="Microsoft Teams", enabled=1, auto_create=1, provider_sends_invites=1,
			use_organizer_account=1, host_email="sales@irsaa.com", tenant_id="T", client_id="C")
		base.update(kw)
		c = D(base)
		c.get_password = lambda f, raise_exception=False: "secret"
		return c

	# ------------------------------------------------------------------ bodies
	def test_teams_body_in_utc_with_attendees(self):
		b = self.m._graph_body(self.conn(), self.doc())
		self.assertEqual(b["start"], {"dateTime": "2026-11-30T07:00:00", "timeZone": "UTC"})  # 10:00 Riyadh
		self.assertEqual(b["end"]["dateTime"], "2026-11-30T07:45:00")
		self.assertEqual([a["type"] for a in b["attendees"]], ["required", "optional"])
		self.assertNotIn("attendees", self.m._graph_body(self.conn(provider_sends_invites=0), self.doc()))

	def test_teams_working_day_recurrence(self):
		r = self.m._graph_recurrence(self.doc(repeat="Every working day", repeat_until=date(2026, 12, 31)))
		self.assertEqual(r["pattern"]["daysOfWeek"], ["monday", "tuesday", "wednesday", "thursday", "sunday"])
		self.assertEqual(r["range"], {"type": "endDate", "startDate": "2026-11-30", "endDate": "2026-12-31"})
		self.assertEqual(self.m._graph_recurrence(self.doc(repeat="Monthly", repeat_every=2))["pattern"],
			{"type": "absoluteMonthly", "interval": 2, "dayOfMonth": 30})

	def test_zoom_body(self):
		b = self.m._zoom_body(self.doc())
		self.assertEqual((b["type"], b["start_time"], b["duration"]), (2, "2026-11-30T07:00:00Z", 45))
		w = self.m._zoom_body(self.doc(repeat="Weekly", repeat_every=2))  # 30 Nov 2026 is a Monday
		self.assertEqual(w["type"], 8)
		self.assertEqual(w["recurrence"], {"type": 2, "repeat_interval": 2, "weekly_days": "2", "end_times": 50})
		wd = self.m._zoom_body(self.doc(repeat="Every working day", repeat_until=date(2026, 12, 31)))
		self.assertEqual(wd["recurrence"]["weekly_days"], "2,3,4,5,1")  # Mon..Thu, Sun in Zoom numbering
		self.assertEqual(wd["recurrence"]["end_date_time"], "2026-12-31T20:59:59Z")

	def test_google_and_webex_bodies(self):
		g = self.m._google_body(self.conn(platform="Google Meet"), self.doc(repeat="Weekly"))
		self.assertEqual(g["start"], {"dateTime": "2026-11-30T07:00:00Z"})
		self.assertEqual(g["recurrence"], ["RRULE:FREQ=WEEKLY;BYDAY=SU,MO,TU,WE,TH"])
		self.assertTrue(g["attendees"][1]["optional"])
		allday = self.m._google_body(self.conn(), self.doc(all_day=1, end_datetime=datetime(2026, 11, 30, 23, 59, 59)))
		self.assertEqual((allday["start"], allday["end"]), ({"date": "2026-11-30"}, {"date": "2026-12-01"}))
		w = self.m._webex_body(self.conn(platform="Webex"), self.doc(), "org@irsaa.com")
		self.assertEqual((w["start"], w["hostEmail"], w["sendEmail"]), ("2026-11-30T07:00:00Z", "org@irsaa.com", True))
		self.assertNotIn("hostEmail", self.m._webex_body(self.conn(platform="Webex"), self.doc(), "sales@irsaa.com"))

	def test_host_choice(self):
		d = self.doc()
		d.organizer_email = "org@irsaa.com"
		self.assertEqual(self.m._pick_host(self.conn(), d, lambda u: True), "org@irsaa.com")
		self.assertEqual(self.m._pick_host(self.conn(), d, lambda u: False), "sales@irsaa.com")
		self.assertEqual(self.m._pick_host(self.conn(use_organizer_account=0), d, lambda u: True), "sales@irsaa.com")

	# ------------------------------------------------------------------ decisions
	def _sync(self, doc, conn=None):
		calls = []
		drivers = {p: (lambda c, d, p=p: calls.append(("create", p)) or (f"{p}-ID", f"https://join/{p}", "org@irsaa.com", {}),
			lambda c, d, p=p: calls.append(("update", p)), lambda c, d, p=p: calls.append(("cancel", p)), None)
			for p in self.m.PLATFORMS}
		with patch.object(self.m, "DRIVERS", drivers), patch.object(self.m, "connection", side_effect=lambda p: conn or self.conn(platform=p)):
			self.m.sync(doc)
		return calls

	def test_create_stores_link(self):
		d = self.doc()
		self.assertEqual(self._sync(d), [("create", "Microsoft Teams")])
		self.assertEqual((d.meeting_link, d.online_meeting_id, d.online_meeting_platform), ("https://join/Microsoft Teams", "Microsoft Teams-ID", "Microsoft Teams"))

	def test_update_only_when_something_changed(self):
		d = self.doc(online_meeting_id="X", online_meeting_platform="Microsoft Teams", online_meeting_host="org@irsaa.com")
		self.assertEqual(self._sync(d), [])
		d.flags.ax_time_changed = True
		self.assertEqual(self._sync(d), [("update", "Microsoft Teams")])

	def test_platform_switch_cancels_then_creates(self):
		d = self.doc(platform="Zoom", online_meeting_id="X", online_meeting_platform="Microsoft Teams")
		self.assertEqual(self._sync(d), [("cancel", "Microsoft Teams"), ("create", "Zoom")])

	def test_cancelled_or_unticked_cancels_and_clears_link(self):
		d = self.doc(status="Cancelled", online_meeting_id="X", online_meeting_platform="Microsoft Teams", meeting_link="https://old")
		self.assertEqual(self._sync(d), [("cancel", "Microsoft Teams")])
		self.assertEqual((d.meeting_link, d.online_meeting_id), ("", None))
		d2 = self.doc(create_online_meeting=0, online_meeting_id="X", online_meeting_platform="Microsoft Teams")
		self.assertEqual(self._sync(d2), [("cancel", "Microsoft Teams")])

	def test_failure_is_stored_not_raised(self):
		d = self.doc()

		def boom(c, x):
			raise self.m.MeetingError("HTTP 403: Access denied")
		drivers = {p: (boom, None, None, None) for p in self.m.PLATFORMS}
		with patch.object(self.m, "DRIVERS", drivers), patch.object(self.m, "connection", return_value=self.conn()):
			self.m.sync(d)
		self.assertIn("HTTP 403", d.stored["online_meeting_error"])
		self.f.msgprint.assert_called()

	def test_not_connected_is_reported(self):
		d = self.doc(platform="Webex")
		with patch.object(self.m, "connection", return_value=None):
			self.m.sync(d)
		self.assertIn("not connected", d.stored["online_meeting_error"])

	def test_zoom_never_claims_to_send_invites(self):
		with patch.object(self.m, "connection", return_value=self.conn(platform="Zoom")):
			self.assertFalse(self.m.provider_handles_invites("Zoom", "123"))
		with patch.object(self.m, "connection", return_value=self.conn()):
			self.assertTrue(self.m.provider_handles_invites("Microsoft Teams", "X"))
			self.assertFalse(self.m.provider_handles_invites("Microsoft Teams", None))


if __name__ == "__main__":
	unittest.main()
