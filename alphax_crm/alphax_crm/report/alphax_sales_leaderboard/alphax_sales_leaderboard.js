// Copyright (c) 2026, AlphaX and contributors
// For license information, please see license.txt

frappe.query_reports["AlphaX Sales Leaderboard"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "territory",
			label: __("Territory"),
			fieldtype: "Link",
			options: "Territory",
		},
	],
	chart_type: "bar",
};

// Common filters: Lead Stage / Status, Date Based On, extra fields (AlphaX CRM Settings > 9.2)
window.alphax_report_scope && window.alphax_report_scope("AlphaX Sales Leaderboard", {"doctype": "Opportunity"});
