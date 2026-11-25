frappe.query_reports["AlphaX Forecast Movement"] = {
    filters: [
    {
        "fieldname": "week_start",
        "label": "Week containing",
        "fieldtype": "Date",
        "default": frappe.datetime.get_today()
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
window.alphax_report_scope && window.alphax_report_scope("AlphaX Forecast Movement", {"doctype": "Opportunity"});
