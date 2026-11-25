frappe.query_reports["AlphaX Expected Close Forecast"] = {
    filters: [
    {
        "fieldname": "from_date",
        "label": "From date",
        "fieldtype": "Date",
        "reqd": 1,
        "default": frappe.datetime.month_start()
    },
    {
        "fieldname": "to_date",
        "label": "To date",
        "fieldtype": "Date",
        "reqd": 1,
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
window.alphax_report_scope && window.alphax_report_scope("AlphaX Expected Close Forecast", {"doctype": "Opportunity"});
