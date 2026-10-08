// Copyright (c) 2026, AlphaX and contributors
// For license information, please see license.txt
//
// Per-Sales-Person breakdown (New Leads / Won / Lost / Quotation Value /
// Win Rate) for the selected period (with an optional comparison). See
// alphax_crm/crm/bi_report.py for the shared period/compare engine.

frappe.query_reports["AlphaX Sales Person Performance BI"] = {
	filters: [
		{
			fieldname: "as_of_date",
			label: __("As Of Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "period_type",
			label: __("Period Type"),
			fieldtype: "Select",
			options: "Daily\nWeekly\nMonthly\nQuarterly\nHalf-Yearly\nYearly",
			default: "Monthly",
			reqd: 1,
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
			fieldtype: "Link",
			options: "AlphaX Business Unit",
		},
	],
	chart_type: "bar",
};
