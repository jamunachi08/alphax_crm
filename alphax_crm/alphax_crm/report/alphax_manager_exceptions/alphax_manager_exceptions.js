frappe.query_reports["AlphaX Manager Exceptions"] = {
    filters: [
    {
        "fieldname": "state",
        "label": "State",
        "fieldtype": "Select",
        "options": "Open\nResolved",
        "default": "Open"
    },
    {
        "fieldname": "executive",
        "label": "Sales executive",
        "fieldtype": "Link",
        "options": "User"
    }
]
};

// Common filters: Lead Stage / Status, Date Based On, extra fields (AlphaX CRM Settings > 9.2)
window.alphax_report_scope && window.alphax_report_scope("AlphaX Manager Exceptions", {"doctype": "Lead"});
