// AlphaX Follow-up Schedule — normally created and edited from the Lead (Follow-ups panel), in a dialog.
frappe.ui.form.on("AlphaX Follow-up Schedule", {
    refresh(frm) {
        if (frm.is_new()) {
            frm.set_intro(__("Schedule follow-ups from the Lead (or Opportunity / PreLead): Follow-up ▸ Schedule Follow-up."), "blue");
            return;
        }
        frm.add_custom_button(__("Edit"), () => window.alphax_open_scheduler({ name: frm.doc.name, on_close: () => frm.reload_doc() })).addClass("btn-primary");
        if (frm.doc.meeting_link) frm.add_custom_button(__("Join"), () => window.open(frm.doc.meeting_link, "_blank", "noopener"));
        if (frm.doc.status === "Scheduled") {
            frm.add_custom_button(__("Log Outcome"), () => {
                const online = ["Microsoft Teams", "Zoom", "Google Meet", "Webex"].includes(frm.doc.platform);
                window.alphax_log_followup({ doctype: frm.doc.reference_doctype, docname: frm.doc.reference_name },
                    { schedule: frm.doc.name, channel: "Meeting", meeting_type: online ? "Online Meeting" : "On-site Meeting",
                      after: () => frm.reload_doc() });
            });
        }
        if (frm.doc.lead) frm.add_custom_button(__("Open Lead"), () => frappe.set_route("Form", "Lead", frm.doc.lead));
        if (frm.doc.reference_doctype !== "Lead") {
            frm.add_custom_button(__("Open {0}", [__(frm.doc.reference_doctype)]), () =>
                frappe.set_route("Form", frm.doc.reference_doctype, frm.doc.reference_name));
        }
        frm.add_custom_button(__("Reminders"), () => frappe.set_route("List", "AlphaX Follow-up Reminder", { schedule: frm.doc.name }));
    },
});
