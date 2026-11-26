// Every occurrence of repeating meetings is shown (crm/schedule.py get_calendar_events).
frappe.views.calendar["AlphaX Follow-up Schedule"] = {
    field_map: { start: "start_datetime", end: "end_datetime", id: "name", title: "subject", allDay: "all_day", color: "color" },
    filters: [
        { fieldtype: "Link", fieldname: "organizer", options: "User", label: __("Organizer") },
        { fieldtype: "Link", fieldname: "lead_owner", options: "User", label: __("Lead Owner") },
        { fieldtype: "Select", fieldname: "platform", label: __("Platform"),
          options: "\nMicrosoft Teams\nZoom\nGoogle Meet\nWebex\nPhone Call\nWhatsApp\nOn-site Visit\nOther" },
    ],
    get_events_method: "alphax_crm.crm.schedule.get_calendar_events",
};
