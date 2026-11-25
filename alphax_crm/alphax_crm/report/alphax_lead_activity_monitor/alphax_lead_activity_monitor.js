frappe.query_reports["AlphaX Lead Activity Monitor"] = {
    filters: [
        {
            fieldname: "status",
            label: __("Status"),
            fieldtype: "MultiSelectList",
            get_data: function () {
                return (frappe.query_reports["AlphaX Lead Activity Monitor"].__status_options || []).map(
                    (o) => ({ value: o, description: "" })
                );
            },
        },
        { fieldname: "lead_owner", label: __("Lead Owner"), fieldtype: "Link", options: "User" },
        { fieldname: "idle_over_days", label: __("Idle Over (days)"), fieldtype: "Int" },
        { fieldname: "only_monitored", label: __("Only Monitored Statuses"), fieldtype: "Check", default: 1 },
        { fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
    ],
    onload: function (report) {
        // Populate the Status multiselect from Lead.status options, and default
        // to the configured default monitored status.
        frappe.db.get_doc("DocType", "Lead").then((d) => {
            const f = (d.fields || []).find((x) => x.fieldname === "status");
            const opts = (f && f.options ? f.options.split("\n") : []).filter(Boolean);
            frappe.query_reports["AlphaX Lead Activity Monitor"].__status_options = opts;
        });
        frappe.call("alphax_crm.crm.tasks.get_default_monitored_status").then((r) => {
            if (r.message) report.set_filter_value("status", [r.message]);
        });
        // Extra field filters come from alphax_report_scope (AlphaX CRM Settings > 9.2).
    },
    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (data && data.overdue === "Yes" && (column.fieldname === "idle_days" || column.fieldname === "overdue")) {
            value = `<span style="color:#b91c1c;font-weight:600">${value}</span>`;
        }
        return value;
    },
};

// Common filters: Lead Stage / Status, Date Based On, extra fields (AlphaX CRM Settings > 9.2)
window.alphax_report_scope && window.alphax_report_scope("AlphaX Lead Activity Monitor", {"doctype": "Lead", "skip": ["ax_lead_stage"]});
