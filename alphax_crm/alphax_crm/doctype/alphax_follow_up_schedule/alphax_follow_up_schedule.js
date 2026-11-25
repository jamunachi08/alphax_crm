// AlphaX Follow-up Schedule — the full editing screen is the Teams-style page alphax-schedule.
frappe.ui.form.on("AlphaX Follow-up Schedule", {
    refresh(frm) {
        if (frm.is_new()) {
            if (frm.doc.reference_doctype && frm.doc.reference_name) {
                frm.add_custom_button(__("Open in Scheduler"), () => window.alphax_schedule_followup(
                    { doctype: frm.doc.reference_doctype, docname: frm.doc.reference_name }));
            }
            return;
        }
        frm.add_custom_button(__("Open in Scheduler"), () => frappe.set_route("alphax-schedule", frm.doc.name)).addClass("btn-primary");
        if (frm.doc.meeting_link) frm.add_custom_button(__("Join"), () => window.open(frm.doc.meeting_link, "_blank", "noopener"));
        if (frm.doc.status === "Scheduled") {
            frm.add_custom_button(__("Log Outcome"), () => {
                const online = ["Microsoft Teams", "Zoom", "Google Meet", "Webex"].includes(frm.doc.platform);
                window.alphax_log_followup({ doctype: frm.doc.reference_doctype, docname: frm.doc.reference_name, reload_doc() {} },
                    { schedule: frm.doc.name, channel: "Meeting", meeting_type: online ? "Online Meeting" : "On-site Meeting",
                      after: () => frm.reload_doc() });
            });
        }
        frm.add_custom_button(__("Reminders"), () => frappe.set_route("List", "AlphaX Follow-up Reminder", { schedule: frm.doc.name }), __("View"));
        frm.add_custom_button(__("Open {0}", [__(frm.doc.reference_doctype)]), () =>
            frappe.set_route("Form", frm.doc.reference_doctype, frm.doc.reference_name), __("View"));
    },
});
