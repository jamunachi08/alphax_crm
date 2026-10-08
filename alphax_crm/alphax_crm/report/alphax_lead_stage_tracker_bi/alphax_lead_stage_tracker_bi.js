// Copyright (c) 2026, AlphaX and contributors
// For license information, please see license.txt
//
// Live, filterable equivalent of the Lead Tracker BI Excel workbook's
// Report tab. See alphax_crm/crm/bi_report.py for the period/compare
// engine shared by this whole report family.

frappe.query_reports["AlphaX Lead Stage Tracker BI"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			description: __("Defaults to one month back. Leave From/To Date blank to use Period Type + As Of Date instead."),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "as_of_date",
			label: __("As Of Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
			description: __("Only used when From Date/To Date are blank."),
		},
		{
			fieldname: "period_type",
			label: __("Period Type"),
			fieldtype: "Select",
			options: "Daily\nWeekly\nMonthly\nQuarterly\nHalf-Yearly\nYearly",
			default: "Monthly",
			description: __("Only used when From Date/To Date are blank."),
		},
		{
			fieldname: "compare_mode",
			label: __("Compare Mode"),
			fieldtype: "Select",
			options: "None\nSame Period Last Year\nSame Quarter Last Year\nFull Last Year",
			default: "None",
		},
		{
			fieldname: "years_back",
			label: __("Years Back"),
			fieldtype: "Select",
			options: "1\n2\n3",
			default: "1",
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
