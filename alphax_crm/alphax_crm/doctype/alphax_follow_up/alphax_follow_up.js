// AlphaX Follow-up — the next step booked from it is an AlphaX Follow-up Schedule (with reminders).
// Change Next Follow-up Date / At / Via / Next Action here and save: the scheduled follow-up moves with it.
frappe.ui.form.on("AlphaX Follow-up", {
    refresh(frm) {
        if (frm.is_new()) return;
        const ref = { doctype: frm.doc.reference_doctype, name: frm.doc.reference_name };
        if (frm.doc.next_schedule) {
            frappe.db.get_value("AlphaX Follow-up Schedule", frm.doc.next_schedule, ["status", "start_datetime", "platform", "meeting_link"]).then((r) => {
                const s = r.message || {};
                if (!s.status) return;
                const when = s.start_datetime ? frappe.datetime.str_to_user(s.start_datetime) : "";
                frm.set_intro(s.status === "Scheduled"
                    ? __("Next step booked as {0}: {1} · {2}. Change the date, time or via below and save to move it (reminders reset), or clear the date to cancel it.",
                        [`<a href="/app/alphax-follow-up-schedule/${encodeURIComponent(frm.doc.next_schedule)}">${frm.doc.next_schedule}</a>`, frappe.utils.escape_html(when), __(s.platform || "")])
                    : __("The booked next step {0} is {1}.", [frm.doc.next_schedule, __(s.status).toLowerCase()]), s.status === "Scheduled" ? "blue" : "orange");
                if (s.meeting_link && s.status === "Scheduled") frm.add_custom_button(__("Join"), () => window.open(s.meeting_link, "_blank", "noopener"));
            });
            frm.add_custom_button(__("Open Scheduled Follow-up"), () => window.alphax_open_scheduler
                && window.alphax_open_scheduler({ name: frm.doc.next_schedule, on_close: () => frm.reload_doc() })).addClass("btn-primary");
        } else if (window.alphax_open_scheduler) {
            frm.add_custom_button(__("Schedule Follow-up"), () => window.alphax_open_scheduler({
                reference_doctype: ref.doctype, reference_name: ref.name, source_follow_up: frm.doc.name,
                start_date: frm.doc.next_follow_up_date || null, on_close: () => frm.reload_doc() }));
        }
        if (ref.doctype && ref.name) frm.add_custom_button(__("Open {0}", [__(ref.doctype)]), () => frappe.set_route("Form", ref.doctype, ref.name));
        if (frm.doc.lead && ref.doctype !== "Lead") frm.add_custom_button(__("Open Lead"), () => frappe.set_route("Form", "Lead", frm.doc.lead));
    },
});
