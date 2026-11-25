frappe.query_reports["AlphaX Owner Activity Summary"] = {
    filters: [
        {
            fieldname: "document_type",
            label: __("Document Type"),
            fieldtype: "Select",
            options: "Lead\nOpportunity\nPreLead",
            default: "Lead",
            reqd: 1,
        },
        { fieldname: "only_overdue", label: __("Only With Overdue"), fieldtype: "Check" },
    ],
    // Extra field filters come from alphax_report_scope (AlphaX CRM Settings > 9.2).
};

// Common filters: Lead Stage / Status, Date Based On, extra fields (AlphaX CRM Settings > 9.2)
window.alphax_report_scope && window.alphax_report_scope("AlphaX Owner Activity Summary", {"doctype": "Lead"});
