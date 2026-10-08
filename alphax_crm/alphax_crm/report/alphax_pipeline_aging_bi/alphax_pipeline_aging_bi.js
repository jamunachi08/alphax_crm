// Copyright (c) 2026, AlphaX and contributors
// For license information, please see license.txt

frappe.query_reports["AlphaX Pipeline Aging (BI)"] = {
	filters: [
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
