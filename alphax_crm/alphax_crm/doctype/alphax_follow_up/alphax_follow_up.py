import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class AlphaXFollowup(Document):
    def validate(self):
        if not self.follow_up_datetime:
            self.follow_up_datetime = now_datetime()
        if not self.agent:
            self.agent = frappe.session.user
        self.title = f"{self.channel or 'Follow-up'} · {self.reference_name}"
        if self.meta.has_field("lead_owner"):
            from alphax_crm.crm.automation import lead_owner_of

            self.lead_owner = lead_owner_of(self.reference_doctype, self.reference_name) or self.lead_owner
        from alphax_crm.crm.followup_hub import set_lead

        set_lead(self)

    def after_insert(self):
        from alphax_crm.crm.followup import process_followup
        process_followup(self)

    def on_update(self):
        # Changing the next step here moves (or books / cancels) the scheduled follow-up it points to.
        from alphax_crm.crm.followup_hub import sync_from_followup

        sync_from_followup(self)
