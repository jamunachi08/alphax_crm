"""Follow-up scheduling (0.49): recurrence, reminder queue, time zones and .ics, without a bench.
python -m unittest tests/test_schedule.py"""
import calendar as _cal
import importlib
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch


class D(dict):
	__getattr__ = dict.get

	def get(self, k, d=None):
		return dict.get(self, k, d)


def get_datetime(v):
	if isinstance(v, datetime):
		return v
	if isinstance(v, date):
		return datetime(v.year, v.month, v.day)
	return datetime.fromisoformat(str(v))


def getdate(v):
	return get_datetime(v).date() if not isinstance(v, date) or isinstance(v, datetime) else v


def add_months(d, n):
	d = get_datetime(d)
	m = d.month - 1 + n
	y, m = d.year + m // 12, m % 12 + 1
	return d.replace(year=y, month=m, day=min(d.day, _cal.monthrange(y, m)[1]))


NOW = datetime(2026, 11, 25, 10, 0)


class ScheduleTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
		f = MagicMock()
		f._ = lambda m: m
		f._dict = D
		u = f.utils
		u.get_datetime.side_effect = get_datetime
		u.getdate.side_effect = getdate
		u.add_months.side_effect = add_months
		u.cint.side_effect = lambda v: int(v or 0)
		u.now_datetime.side_effect = lambda: NOW
		u.escape_html.side_effect = lambda s: str(s)
		u.strip_html.side_effect = lambda s: s
		u.get_url.return_value = "https://erp.example.com"
		u.get_url_to_form.side_effect = lambda dt, n: f"https://erp.example.com/app/x/{n}"
		u.get_fullname.side_effect = lambda x: x
		u.get_system_timezone.return_value = "Asia/Riyadh"
		f.db.get_value.side_effect = lambda dt, n, fld=None, *a, **k: 1 if fld == "enabled" else f"{n}@x.com"
		cls.f = f
		auto = MagicMock()
		auto.calendar.return_value = D(days={6, 0, 1, 2, 3})  # KSA: Sunday–Thursday
		auto.is_working_day.side_effect = lambda d, cal=None: d.weekday() in cal.days
		cls.inserted = []
		cls.mods = patch.dict(sys.modules, {"frappe": f, "frappe.utils": u, "alphax_crm.crm.utils": MagicMock(),
			"alphax_crm.crm.automation": auto})
		cls.mods.start()
		cls.s = importlib.import_module("alphax_crm.crm.schedule")
		cls.s.now_datetime = lambda: NOW
		import alphax_crm.crm as pkg

		pkg.automation = auto

	@classmethod
	def tearDownClass(cls):
		cls.mods.stop()

	def doc(self, **kw):
		base = dict(name="FUS-1", subject="Demo", status="Scheduled", start_datetime=datetime(2026, 11, 26, 10, 0),
			end_datetime=datetime(2026, 11, 26, 10, 30), repeat="Does not repeat", repeat_every=1, repeat_until=None,
			organizer="org@x", lead_owner="owner@x", attendees=[], reminders=[], all_day=0, platform="Microsoft Teams",
			meeting_link="https://teams.microsoft.com/l/meetup-join/abc", location="", agenda="")
		base.update(kw)
		return D(base)

	# --------------------------------------------------------------- recurrence
	def test_single(self):
		self.assertEqual(len(self.s.occurrences(self.doc(), NOW, NOW + timedelta(days=5))), 1)
		self.assertEqual(self.s.occurrences(self.doc(), datetime(2026, 11, 27), datetime(2026, 12, 1)), [])

	def test_every_other_day_until(self):
		d = self.doc(repeat="Daily", repeat_every=2, repeat_until=date(2026, 12, 2))
		starts = [o[0].day for o in self.s.occurrences(d, NOW, NOW + timedelta(days=30))]
		self.assertEqual(starts, [26, 28, 30, 2])

	def test_working_days_follow_ksa_week(self):
		d = self.doc(repeat="Every working day", start_datetime=datetime(2026, 11, 26, 9), end_datetime=datetime(2026, 11, 26, 9, 30))
		days = [o[0].strftime("%a") for o in self.s.occurrences(d, NOW, datetime(2026, 12, 3, 23))]
		self.assertEqual(days, ["Thu", "Sun", "Mon", "Tue", "Wed", "Thu"])

	def test_monthly_end_of_month(self):
		d = self.doc(repeat="Monthly", start_datetime=datetime(2027, 1, 31, 9), end_datetime=datetime(2027, 1, 31, 10))
		got = [o[0].date() for o in self.s.occurrences(d, datetime(2027, 1, 1), datetime(2027, 4, 30, 23))]
		self.assertEqual(got, [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)])

	def test_long_running_series_jumps_to_today(self):
		d = self.doc(repeat="Weekly", start_datetime=datetime(2020, 1, 1, 9), end_datetime=datetime(2020, 1, 1, 10))
		occ = self.s.occurrences(d, NOW, NOW + timedelta(days=14))
		# Wed 09:00 weekly since 2020: today's ends exactly now, then 2 Dec and 9 Dec
		self.assertEqual([o[0].date() for o in occ], [date(2026, 11, 25), date(2026, 12, 2), date(2026, 12, 9)])

	# --------------------------------------------------------------- reminders
	def _rebuild(self, doc, kept=()):
		queued = []
		self.f.get_all.return_value = list(kept)
		with patch.object(self.s, "_queue", side_effect=lambda *a: queued.append(a)):
			self.s.rebuild_reminders(doc, NOW)
		return queued

	def test_rules_times_and_people(self):
		doc = self.doc(reminders=[D(remind_before="15 minutes before", popup=1, email=1), D(remind_before="1 day before", popup=0, email=1)],
			attendees=[D(attendee_type="Internal", user="sara@x"), D(attendee_type="External", email="client@c.com")])
		q = self._rebuild(doc)
		# 1 day before 26 Nov 10:00 is 25 Nov 10:00 == now -> late; only the 15-minute rule is queued normally
		normal = [x for x in q if x[5] == "15 minutes before"]
		self.assertEqual({x[1] for x in normal}, {"org@x", "owner@x", "sara@x"})
		self.assertTrue(all(x[4] == datetime(2026, 11, 26, 9, 45) for x in normal))
		late = [x for x in q if x[5] == self.s.LATE_RULE]
		self.assertEqual(len(late), 3)
		self.assertEqual((late[0][6], late[0][7]), (0, 1))  # email only, like the rule it stands for

	def test_already_shown_not_repeated(self):
		doc = self.doc(reminders=[D(remind_before="15 minutes before", popup=1, email=1)])
		kept = [D(name="R1", status="Dismissed", user="org@x", occurrence_start=datetime(2026, 11, 26, 10), remind_before="15 minutes before")]
		q = self._rebuild(doc, kept)
		self.assertEqual({x[1] for x in q}, {"owner@x"})

	def test_cancelled_meeting_queues_nothing(self):
		doc = self.doc(status="Cancelled", reminders=[D(remind_before="15 minutes before", popup=1, email=1)])
		self.assertEqual(self._rebuild(doc), [])

	# --------------------------------------------------------------- time zones and .ics
	def test_time_zone_conversion(self):
		self.assertEqual(self.s.convert(datetime(2026, 11, 26, 9, 0), "Europe/London", "Asia/Riyadh"), datetime(2026, 11, 26, 12, 0))
		self.assertEqual(self.s.convert(datetime(2026, 11, 26, 9, 0), "Asia/Riyadh", "Asia/Riyadh"), datetime(2026, 11, 26, 9, 0))

	def test_ics(self):
		doc = self.doc(repeat="Every working day", repeat_until=date(2026, 12, 31), subject="Review; pricing, scope",
			attendees=[D(attendee_type="External", email="client@c.com", full_name="Client", attendance="Optional")],
			reminders=[D(remind_before="1 day before", email=1), D(remind_before="15 minutes before", popup=1)], agenda="Line 1\nLine 2 " + "x" * 120)
		ics = self.s.build_ics(doc, internal=False)
		self.assertIn("DTSTART:20261126T070000Z", ics)  # 10:00 Riyadh
		self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,SU;UNTIL=20261231T205959Z", ics)
		self.assertIn("SUMMARY:Review\\; pricing\\, scope", ics)
		self.assertIn("ROLE=OPT-PARTICIPANT", ics)
		self.assertIn("TRIGGER:-PT15M", ics)
		self.assertNotIn("Open in ERP", ics.replace("\r\n ", ""))  # clients get no internal link
		self.assertTrue(all(len(l.encode()) <= 75 for l in ics.split("\r\n")))
		self.assertIn("Open in ERP", self.s.build_ics(doc, internal=True).replace("\r\n ", ""))
		self.assertIn("STATUS:CANCELLED", self.s.build_ics(doc, method="CANCEL"))

	def test_all_day_ics_uses_dates(self):
		doc = self.doc(all_day=1, start_datetime=datetime(2026, 11, 26), end_datetime=datetime(2026, 11, 26, 23, 59, 59))
		ics = self.s.build_ics(doc)
		self.assertIn("DTSTART;VALUE=DATE:20261126", ics)
		self.assertIn("DTEND;VALUE=DATE:20261127", ics)


if __name__ == "__main__":
	unittest.main()
