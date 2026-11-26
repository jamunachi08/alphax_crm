"""Common report filters (0.47): isolated tests against a tiny in-memory database.
python -m unittest tests/test_report_scope.py"""
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class D(dict):
	__getattr__ = dict.get


class DF(D):
	pass


class Meta:
	def __init__(self, fields):
		self.fields = [DF(fieldname=k, **v) for k, v in fields.items()]

	def get_field(self, fn):
		return next((f for f in self.fields if f.fieldname == fn), None)

	def has_field(self, fn):
		return self.get_field(fn) is not None


METAS = {
	"Lead": Meta({"status": {"fieldtype": "Select", "options": "Lead\nQuotation\nPostponed"},
		"custom_lead_status": {"fieldtype": "Select", "options": "Lead\nProspect"},
		"territory": {"fieldtype": "Link", "options": "Territory"},
		"expected_closing_date": {"fieldtype": "Date"}, "alphax_prospect": {"fieldtype": "Data"}}),
	"Opportunity": Meta({"status": {"fieldtype": "Select", "options": "Open\nLost"},
		"territory": {"fieldtype": "Link", "options": "Territory"}}),
	"Quotation": Meta({"status": {"fieldtype": "Select", "options": "Open\nLost"}}),
	"AlphaX PreLead": Meta({}),
}

DB = {
	"Lead": [D(name="L1", status="Quotation", custom_lead_status="Prospect", territory="Riyadh", creation="2026-11-01 10:00:00", alphax_prospect="P1"),
		D(name="L2", status="Postponed", custom_lead_status="Cold Lead", territory="Jeddah", creation="2026-10-01 10:00:00"),
		D(name="L3", status="Quotation", custom_lead_status="Prospect", territory="Jeddah", creation="2026-11-20 10:00:00")],
	"Opportunity": [D(name="O1", opportunity_from="Lead", party_name="L1", status="Open", creation="2026-11-02 00:00:00"),
		D(name="O2", opportunity_from="Lead", party_name="L2", status="Lost", creation="2026-11-03 00:00:00"),
		D(name="O3", opportunity_from="Customer", party_name="C3", status="Open", creation="2026-11-04 00:00:00")],
	"Customer": [D(name="C3", lead_name="L3")],
	"Quotation": [],
	"AlphaX PreLead": [D(name="P1")],
}


def match(row, cond):
	for k, v in cond.items():
		val = row.get(k)
		if isinstance(v, list):
			op, arg = v
			if op == "in" and val not in arg:
				return False
			if op == "between" and not (arg[0] <= (val or "") <= arg[1]):
				return False
			if op == ">=" and not (val or "") >= arg:
				return False
			if op == "<=" and not (val or "") <= arg:
				return False
			if op == "like" and arg.strip("%") not in (val or ""):
				return False
		elif val != v:
			return False
	return True


def get_all(dt, filters=None, pluck=None, fields=None, as_list=False, **kw):
	rows = [r for r in DB.get(dt, []) if match(r, filters or {})]
	if pluck:
		return [r.get(pluck) for r in rows]
	if as_list:
		return [tuple(r.get(f) for f in fields) for r in rows]
	return [D({f: r.get(f) for f in (fields or ["name"])}) for r in rows]


class ReportScopeTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
		f = MagicMock()
		f._ = lambda m: m
		f._dict = D
		f.get_all.side_effect = get_all
		f.get_meta.side_effect = lambda dt: METAS[dt]
		f.db.exists.return_value = True
		f.parse_json.side_effect = __import__("json").loads
		f.utils.cint.side_effect = lambda n: int(n or 0)
		cls.mods = patch.dict(sys.modules, {"frappe": f, "frappe.utils": f.utils, "alphax_crm.crm.utils": MagicMock()})
		cls.mods.start()
		cls.rs = importlib.import_module("alphax_crm.crm.report_scope")

	@classmethod
	def tearDownClass(cls):
		cls.mods.stop()

	def test_no_scope_filters_means_no_restriction(self):
		self.assertIsNone(self.rs.allowed(D(from_date="2026-01-01"), "Lead"))
		rows = [{"lead": "L1"}, {"lead": None}]
		self.assertEqual(self.rs.filter_rows(D(), rows), rows)

	def test_lead_stage_and_status_multi(self):
		self.assertEqual(self.rs.allowed(D(ax_lead_stage='["Quotation"]'), "Lead"), {"L1", "L3"})
		self.assertEqual(self.rs.allowed(D(ax_lead_stage=["Quotation", "Postponed"], ax_lead_status=["Cold Lead"]), "Lead"), {"L2"})

	def test_date_based_on_inclusive_end_day(self):
		f = D(ax_date_field="creation", ax_from_date="2026-11-01", ax_to_date="2026-11-20")
		self.assertEqual(self.rs.allowed(f, "Lead"), {"L1", "L3"})
		f = D(ax_date_field="not_a_field", ax_from_date="2026-11-01")
		self.assertIsNone(self.rs.allowed(f, "Lead"))

	def test_extra_field_on_lead(self):
		self.assertEqual(self.rs.allowed(D(axf_lead__territory="Jeddah"), "Lead"), {"L2", "L3"})

	def test_lead_filters_reach_opportunities_including_via_customer(self):
		f = D(ax_lead_stage=["Quotation"])
		self.assertEqual(self.rs.allowed(f, "Opportunity"), {"O1", "O3"})
		f = D(ax_lead_stage=["Quotation"], ax_status=["Open"], axf_opportunity__territory=None)
		self.assertEqual(self.rs.allowed(f, "Opportunity"), {"O1", "O3"})
		self.assertEqual(self.rs.allowed(D(ax_status=["Lost"]), "Opportunity"), {"O2"})

	def test_restrict_intersects_existing_name_filter(self):
		cond = {"name": ["in", ["L1", "L2"]]}
		self.rs.restrict(D(ax_lead_stage=["Quotation"]), "Lead", cond)
		self.assertEqual(cond["name"], ["in", ["L1"]])
		cond = {}
		self.rs.restrict(D(ax_lead_stage=["Won"]), "Lead", cond)
		self.assertEqual(cond["name"], ["in", [self.rs.NO_MATCH]])

	def test_follow_up_rows_by_reference_doctype(self):
		rows = [{"reference_doctype": "Lead", "reference_name": "L1"},
			{"reference_doctype": "Lead", "reference_name": "L2"},
			{"reference_doctype": "Opportunity", "reference_name": "O3"},
			{"reference_doctype": "AlphaX PreLead", "reference_name": "P1"}]
		out = self.rs.filter_rows(D(ax_lead_stage=["Quotation"]), rows, "Lead", "reference_name", doctype_key="reference_doctype")
		self.assertEqual([r["reference_name"] for r in out], ["L1", "O3", "P1"])

	def test_describe_mentions_active_filters(self):
		text = self.rs.describe(D(ax_lead_stage=["Quotation"], axf_lead__territory="Riyadh"), "Lead")
		self.assertIn("Quotation", text)
		self.assertIn("1 extra field", text)
		self.assertEqual(self.rs.describe(D(), "Lead"), "")

	def test_configured_field_doctype_choice(self):
		row = {"document_type": "", "metas": {"Lead": {}, "Opportunity": {}}}
		self.assertEqual(self.rs.field_doctype(row, "Opportunity"), "Opportunity")
		self.assertEqual(self.rs.field_doctype(row, "Quotation"), "Lead")
		self.assertIsNone(self.rs.field_doctype({"document_type": "Opportunity", "metas": {"Opportunity": {}}}, "Quotation"))


if __name__ == "__main__":
	unittest.main()
