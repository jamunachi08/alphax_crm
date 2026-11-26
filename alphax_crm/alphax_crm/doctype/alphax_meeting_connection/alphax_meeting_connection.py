from frappe.model.document import Document


class AlphaXMeetingConnection(Document):
    def validate(self):
        from alphax_crm.crm.meeting_connect import validate_connection

        validate_connection(self)
