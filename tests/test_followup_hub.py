"""Follow-ups in one place (0.50): booking next dates, Lead links, Lead dashboard. No bench needed.
python -m unittest tests/test_followup_hub.py"""
import importlib
import sys
import unittest
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import MagicMock, patch


class D(dict):
	__getattr__ = dict.get

	def get(self, k, d=None):
		return dict.get(self, k, d)


class Doc(D):
	def __init__(self, **kw):
		super().__init__(**kw)
		self.flags = D()


class HubTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
		f = MagicMock()
		f._ = lambda m: m
		u = f.utils
		u.cint.side_effect = lambda v: int(v or 0)
		u.getdate.side_effect = lambda v=None: v if isinstance(v, date) else date.fromisoformat(str(v))
		u.get_time.side_effect = lambda v: v if isinstance(v, time) else time.fromisoformat(str(v))
		u.escape_html.side_effect = lambda s: s
		cls.f = f
		cls.settings = D()
		utils = MagicMock()
		utils.get_settings.side_effect = lambda: cls.settings
		sched = MagicMock()
		sched.default_duration.return_value = 30
		sched.system_tz.return_value = "Asia/Riyadh"
		cls.mods = patch.dict(sys.modules, {"frappe": f, "frappe.utils": u, "alphax_crm.crm.utils": utils,
			"alphax_crm.crm.schedule": sched})
		cls.mods.start()
		import alphax_crm.crm as pkg

		pkg.schedule = sched
		cls.hub = importlib.import_module("alphax_crm.crm.followup_hub")

	@classmethod
	def tearDownClass(cls):
		cls.mods.stop()

	def setUp(self):
		self.f.get_doc.reset_mock()
		self.f.db.set_value.reset_mock()
		self.created = []

		def get_doc(d):
			m = MagicMock()
			m.name = "FUS-1"
			self.created.append(d)
			return m
		self.f.get_doc.side_effect = get_doc
		self.settings.clear()

	def fu(self, **kw):
		base = dict(name="FU-1", reference_doctype="Lead", reference_name="L1", next_follow_up_date=date(2026, 11, 30),
			next_follow_up_time="14:30:00", next_follow_up_via="Zoom", next_action="Send revised pricing", agent="raad@x")
		base.update(kw)
		return Doc(**base)

	def test_next_date_is_booked_with_time_and_via(self):
		self.assertEqual(self.hub.book_next(self.fu()), "FUS-1")
		d = self.created[0]
		self.assertEqual(d["start_datetime"], datetime(2026, 11, 30, 14, 30))
		self.assertEqual(d["end_datetime"], datetime(2026, 11, 30, 15, 0))
		self.assertEqual((d["platform"], d["subject"], d["organizer"], d["source_follow_up"]), ("Zoom", "Send revised pricing", "raad@x", "FU-1"))
		self.f.db.set_value.assert_called_with("AlphaX Follow-up", "FU-1", "next_schedule", "FUS-1", update_modified=False)

	def test_defaults_when_time_and_title_missing(self):
		self.hub.book_next(self.fu(next_follow_up_time=None, next_follow_up_via="Phone Call", next_action=""))
		d = self.created[0]
		self.assertEqual(d["start_datetime"], datetime(2026, 11, 30, 10, 0))
		self.assertEqual(d["platform"], "Call")
		self.assertEqual(d["subject"], "Call follow-up")

	def test_not_booked_twice_or_when_switched_off(self):
		self.assertIsNone(self.hub.book_next(self.fu(next_schedule="FUS-9")))
		self.assertIsNone(self.hub.book_next(self.fu(next_follow_up_date=None)))
		self.settings["schedule_book_next_dates"] = 0
		self.assertIsNone(self.hub.book_next(self.fu()))
		self.assertEqual(self.created, [])

	def test_lead_dashboard_adds_follow_ups_once(self):
		data = {"fieldname": "lead", "transactions": [{"items": ["Opportunity", "Quotation"]}]}
		out = self.hub.lead_dashboard(data)
		self.assertEqual(out["transactions"][0]["items"], ["AlphaX Follow-up Schedule", "AlphaX Follow-up"])
		self.assertEqual(len(self.hub.lead_dashboard(out)["transactions"]), 2)

	def test_lead_dashboard_other_fieldname(self):
		out = self.hub.lead_dashboard({"fieldname": "party_name", "transactions": []})
		self.assertEqual(out["non_standard_fieldnames"]["AlphaX Follow-up"], "lead")


if __name__ == "__main__":
	unittest.main()
