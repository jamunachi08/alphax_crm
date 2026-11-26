from alphax_crm.crm import schedule as engine
from frappe.model.document import Document


class AlphaXFollowupSchedule(Document):
    def validate(self):
        engine.validate_schedule(self)

    def on_update(self):
        engine.on_schedule_update(self)

    def on_trash(self):
        engine.on_schedule_trash(self)
