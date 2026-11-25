"""Process-controlled stages (0.46): isolated rule tests, no bench needed.
python -m unittest tests/test_process_stages.py"""
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class Settings(dict):
	def get(self, k, d=None):
		return dict.get(self, k, d)


class Doc(dict):
	def __init__(self, name, stage, new=False, **kw):
		super().__init__(name=name, status=stage, **kw)
		self.name, self._new, self.flags = name, new, {}

	def get(self, k, d=None):
		return dict.get(self, k, d)

	def is_new(self):
		return self._new


class Blocked(Exception):
	pass


class ProcessStagesTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
		cls.frappe = MagicMock()
		cls.frappe.whitelist.side_effect = lambda **kw: (lambda fn: fn)
		cls.frappe._ = lambda m: m
		cls.frappe.utils.cint.side_effect = lambda n: int(n or 0)
		cls.frappe.utils.escape_html.side_effect = lambda s: s.replace("<", "&lt;")
		cls.frappe.render_template.side_effect = lambda t, c: t.replace("{{ lead }}", c["lead"]).replace("{{ stage }}", c["stage"])
		cls.mods = patch.dict(sys.modules, {
			"frappe": cls.frappe, "frappe.utils": cls.frappe.utils,
			"alphax_crm.crm.automation": MagicMock(), "alphax_crm.crm.utils": MagicMock(),
		})
		cls.mods.start()
		cls.ps = importlib.import_module("alphax_crm.crm.process_stages")

	@classmethod
	def tearDownClass(cls):
		cls.mods.stop()

	def setUp(self):
		f = self.frappe
		f.flags.in_import = f.flags.in_patch = f.flags.in_install = f.flags.in_migrate = False
		f.local.lang = "en"
		f.db.exists.return_value = True
		f.db.get_value.return_value = "Qualified lead"
		f.throw.reset_mock()
		f.throw.side_effect = Blocked
		self.ps.auto.quotations_for_lead.reset_mock()
		self.ps.auto.quotations_for_lead.return_value = []
		self.s = Settings(lost_quotation_stage_value="Lost Quotation")

	def test_quotation_without_linked_quotation_is_blocked(self):
		with self.assertRaises(Blocked):
			self.ps.enforce(Doc("L1", "Quotation"), self.s)
		msg = self.frappe.throw.call_args[0][0]
		self.assertIn('dir="rtl"', msg)
		self.assertIn("L1", msg)
		self.assertEqual(self.ps.auto.quotations_for_lead.call_args[0][1], {"docstatus": 1})

	def test_quotation_with_submitted_quotation_is_allowed(self):
		self.ps.auto.quotations_for_lead.return_value = [{"name": "SAL-QTN-1"}]
		self.ps.enforce(Doc("L1", "Quotation"), self.s)
		self.frappe.throw.assert_not_called()

	def test_drafts_count_when_configured(self):
		self.s["process_stage_quotation_accepts"] = "Draft or submitted quotation"
		self.ps.auto.quotations_for_lead.return_value = [{"name": "SAL-QTN-1"}]
		self.ps.enforce(Doc("L1", "Quotation"), self.s)
		self.assertEqual(self.ps.auto.quotations_for_lead.call_args[0][1], {"docstatus": ["<", 2]})

	def test_lost_quotation_always_blocked_by_hand(self):
		self.ps.auto.quotations_for_lead.return_value = [{"name": "SAL-QTN-1"}]
		with self.assertRaises(Blocked):
			self.ps.enforce(Doc("L1", "Lost Quotation"), self.s)

	def test_lead_already_at_stage_stays_editable(self):
		self.frappe.db.get_value.return_value = "Quotation"
		self.ps.enforce(Doc("L1", "Quotation"), self.s)
		self.frappe.db.get_value.return_value = "Lost Quotation"
		self.ps.enforce(Doc("L1", "Lost Quotation"), self.s)
		self.frappe.throw.assert_not_called()

	def test_system_moves_import_and_switch_off_pass(self):
		d = Doc("L1", "Lost Quotation")
		d.flags["alphax_system_stage"] = True
		self.ps.enforce(d, self.s)
		self.frappe.flags.in_import = True
		self.ps.enforce(Doc("L1", "Lost Quotation"), self.s)
		self.frappe.flags.in_import = False
		self.ps.enforce(Doc("L1", "Lost Quotation"), Settings(process_stage_guard_enabled=0))
		self.frappe.throw.assert_not_called()

	def test_other_stages_untouched(self):
		for st in ("Interested", "Postponed", "Lost with reason", "Won"):
			self.ps.enforce(Doc("L1", st), self.s)
		self.frappe.throw.assert_not_called()

	def test_custom_messages_and_language_order(self):
		self.s.update(process_stage_msg_lost_quotation_en="EN {{ lead }}", process_stage_msg_lost_quotation_ar="AR {{ lead }}")
		m = self.ps.message("lost_quotation", "L9", None, self.s)
		self.assertEqual((m["en"], m["ar"]), ("EN L9", "AR L9"))
		self.assertLess(m["message"].index("EN L9"), m["message"].index("AR L9"))
		self.frappe.local.lang = "ar"
		m = self.ps.message("lost_quotation", "L9", None, self.s)
		self.assertLess(m["message"].index("AR L9"), m["message"].index("EN L9"))
		self.assertTrue(m["title"].startswith(self.ps.TITLE_AR))

	def test_blank_message_uses_built_in_text(self):
		m = self.ps.message("quotation", "L2", None, Settings(process_stage_msg_quotation_en="  "))
		self.assertIn("submitted", m["en"])
		self.assertIn("عرض سعر", m["ar"])

	def test_form_check_returns_message_without_throwing(self):
		self.frappe.has_permission.return_value = True
		r = self.ps.check_stage_selection(lead="L1", stage="Quotation")
		self.assertEqual((r["allowed"], r["kind"]), (0, "quotation"))
		self.ps.auto.quotations_for_lead.return_value = [{"name": "Q"}]
		self.assertEqual(self.ps.check_stage_selection(lead="L1", stage="Quotation")["allowed"], 1)


if __name__ == "__main__":
	unittest.main()
