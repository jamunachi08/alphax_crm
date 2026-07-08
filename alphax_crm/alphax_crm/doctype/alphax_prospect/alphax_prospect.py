"""AlphaX Prospect — pre-lead staging record for cold calling lists.

Deliberately thin: contact fields are plain Data (no Link masters), so bulk
dumps are frictionless. Masters are created only at conversion, when an
operator has judged the record genuine (see api/prospect.py).
"""

from frappe.model.document import Document

from alphax_crm.api.lead_import import _normalize_phone


class AlphaXProspect(Document):
    def validate(self):
        self.prospect_name = " ".join(
            p for p in ((self.first_name or "").strip(), (self.last_name or "").strip()) if p
        )
        for f in ("mobile_no", "phone"):
            if self.get(f):
                self.set(f, _normalize_phone(self.get(f)))
