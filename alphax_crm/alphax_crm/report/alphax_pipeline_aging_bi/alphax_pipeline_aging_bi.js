// Copyright (c) 2026, AlphaX and contributors
// For license information, please see license.txt

frappe.query_reports["AlphaX Pipeline Aging BI"] = {
	filters: [
		{
			fieldname: "as_of_date",
			label: __("As Of Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
			description: __("Reconstructs the pipeline as it stood on this date, from each Lead's logged Lead Stage history."),
		},
		{
			fieldname: "lead_owner",
			label: __("Sales Person"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "source",
			label: __("Source"),
			fieldtype: "Link",
			options: "Lead Source",
		},
		{
			fieldname: "city",
			label: __("City"),
			fieldtype: "Data",
		},
		{
			fieldname: "custom_business_lead_unit",
			label: __("Business Unit"),
			fieldtype: "Data",
			description: __("Matches this site's Business Unit value on the Lead exactly (not a lookup list -- that master is a per-lead table, not a single linkable record)."),
		},
	],
	chart_type: "bar",
};
