"""Lead Owner on activities and document links in notifications (0.48): isolated tests.
python -m unittest tests/test_owner_and_links.py"""
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class D(dict):
	__getattr__ = dict.get


class Meta:
	def __init__(self, fields):
		self.f = set(fields)

	def has_field(self, fn):
		return fn in self.f


LEADS = {"L1": D(name="L1", lead_owner="raad@irsaa.com", owner="admin@x"), "L2": D(name="L2", lead_owner=None, owner="sara@irsaa.com")}
OPPS = {"O1": D(name="O1", opportunity_owner="opp@irsaa.com", owner="admin@x"), "O9": D(name="O9", opportunity_owner="lone@irsaa.com", owner="admin@x")}


class OwnerLinksTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
		f = MagicMock()
		f._ = lambda m: m
		f._dict = D
		f.utils.escape_html.side_effect = lambda s: str(s).replace("<", "&lt;")
		f.utils.get_fullname.side_effect = lambda u: {"raad@irsaa.com": "Raad Haddad"}.get(u, u)
		f.utils.get_url_to_form.side_effect = lambda dt, n: f"https://site/app/{dt.lower()}/{n}"
		f.get_meta.side_effect = lambda dt: Meta({"Lead": ["lead_owner"], "Opportunity": ["opportunity_owner"]}.get(dt, []))

		def exists(dt, name=None):
			return name in {"Lead": LEADS, "Opportunity": OPPS, "Quotation": {"Q1": 1}}.get(dt, {}) if name else True
		f.db.exists.side_effect = exists

		def get_value(dt, name, fields, as_dict=False):
			src = {"Lead": LEADS, "Opportunity": OPPS}[dt].get(name) or D()
			if isinstance(fields, list):
				return D({k: src.get(k) for k in fields}) if as_dict else [src.get(k) for k in fields]
			return src.get(fields)
		f.db.get_value.side_effect = get_value

		def get_all(dt, filters=None, fields=None, **kw):
			src = {"Lead": LEADS, "Opportunity": OPPS}.get(dt, {})
			names = (filters or {}).get("name", ["in", list(src)])[1]
			return [D({k: src[n].get(k) for k in fields}) for n in names if n in src]
		f.get_all.side_effect = get_all
		cls.f = f
		scope = MagicMock()
		scope.leads_for.side_effect = lambda dt, names: {n: ({"O1": "L1"}.get(n) if dt == "Opportunity" else n) for n in names}
		cls.mods = patch.dict(sys.modules, {"frappe": f, "frappe.utils": f.utils, "alphax_crm.crm.utils": MagicMock(),
			"alphax_crm.crm.report_scope": scope})
		cls.mods.start()
		cls.auto = importlib.import_module("alphax_crm.crm.automation")
		cls.auto.lead_for_quotation = lambda q: "L1" if q == "Q1" else None
		cls.emails = importlib.import_module("alphax_crm.crm.emails")

	@classmethod
	def tearDownClass(cls):
		cls.mods.stop()

	def test_owner_resolution(self):
		self.assertEqual(self.auto.lead_owner_of("Lead", "L1"), "raad@irsaa.com")
		self.assertEqual(self.auto.lead_owner_of("Lead", "L2"), "sara@irsaa.com")  # falls back to creator
		self.assertEqual(self.auto.lead_owner_of("Opportunity", "O1"), "raad@irsaa.com")  # its Lead's owner wins
		self.assertEqual(self.auto.lead_owner_of("Opportunity", "O9"), "lone@irsaa.com")  # no Lead: its own owner
		self.assertEqual(self.auto.lead_owner_of("Quotation", "Q1"), "raad@irsaa.com")

	def test_bulk_owners(self):
		out = self.auto.lead_owners({("Lead", "L1"), ("Opportunity", "O1"), ("Opportunity", "O9")})
		self.assertEqual(out[("Lead", "L1")], "raad@irsaa.com")
		self.assertEqual(out[("Opportunity", "O1")], "raad@irsaa.com")
		self.assertEqual(out[("Opportunity", "O9")], "lone@irsaa.com")

	def test_footer_adds_links_and_owner(self):
		html = self.emails.with_document_footer("<p>Hi</p>", "L1", "Quotation", "Q1")
		self.assertIn("https://site/app/lead/L1", html)
		self.assertIn("https://site/app/quotation/Q1", html)
		self.assertIn("Raad Haddad (raad@irsaa.com)", html)

	def test_footer_does_not_repeat_existing_link_or_owner(self):
		body = '<p><a href="https://site/app/lead/L1">Open</a></p>'
		html = self.emails.with_document_footer(body, "L1")
		self.assertEqual(html.count("https://site/app/lead/L1"), 1)
		self.assertIn("Lead Owner", html)
		again = self.emails.with_document_footer(html, "L1")
		self.assertEqual(again, html)

	def test_no_document_no_footer(self):
		self.assertEqual(self.emails.with_document_footer("<p>x</p>"), "<p>x</p>")


if __name__ == "__main__":
	unittest.main()
