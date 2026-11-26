// AlphaX CRM — follow-up actions shared by Lead, Opportunity and PreLead (0.50.0).
// One way to record anything that happened (Log Follow-up; a call is a follow-up with channel Call) and one way
// to plan what happens next (the next date is booked as a scheduled follow-up with reminders). Everything shows
// in the Follow-ups panel on the record's Activities tab (alphax_followup_hub.js).

const AX_VIA = ["Call", "Microsoft Teams", "Zoom", "Google Meet", "Webex", "WhatsApp", "Email", "On-site Visit", "Other"];

window.alphax_log_followup = function (frm, opts) {
    opts = opts || {};
    const is_call = (opts.channel || "Call") === "Call";
    const d = new frappe.ui.Dialog({
        title: opts.title || (opts.channel === "Call" && opts.call ? __("Log a Call") : __("Log Follow-up")),
        fields: [
            { fieldtype: "Select", fieldname: "channel", label: __("Channel"),
              options: "Call\nEmail\nWhatsApp\nMeeting\nVisit\nSMS\nOther", default: opts.channel || "Call", reqd: 1 },
            { fieldtype: "Select", fieldname: "meeting_type", label: __("Meeting Type"),
              options: "\nOnline Meeting\nOn-site Meeting", default: opts.meeting_type || "",
              depends_on: 'eval:doc.channel=="Meeting"', mandatory_depends_on: 'eval:doc.channel=="Meeting"' },
            { fieldtype: "Select", fieldname: "direction", label: __("Direction"), options: "Outgoing\nIncoming", default: "Outgoing" },
            { fieldtype: "Column Break" },
            { fieldtype: "Select", fieldname: "outcome", label: __("Outcome"),
              options: "Connected\nNo Answer\nBusy\nLeft Voicemail\nRescheduled\nInterested\nNot Interested\nCallback Requested\nCompleted",
              default: opts.schedule ? "Completed" : "Connected" },
            { fieldtype: "Duration", fieldname: "duration", label: __("Duration"), hide_days: 1,
              depends_on: 'eval:["Call","Meeting","Visit"].includes(doc.channel)' },
            { fieldtype: "Section Break" },
            { fieldtype: "Small Text", fieldname: "summary", label: __("What happened"), reqd: 1 },
            { fieldtype: "Section Break", label: __("Next follow-up"),
              description: __("Book the next step now: it gets reminders (pop-up + email) and shows under Coming up.") },
            { fieldtype: "Date", fieldname: "next_follow_up_date", label: __("Date") },
            { fieldtype: "Column Break" },
            { fieldtype: "Time", fieldname: "next_follow_up_time", label: __("At"), default: "10:00:00",
              depends_on: "eval:doc.next_follow_up_date" },
            { fieldtype: "Column Break" },
            { fieldtype: "Select", fieldname: "next_follow_up_via", label: __("Via"), options: AX_VIA.join("\n"),
              default: is_call ? "Call" : (opts.channel === "Meeting" ? "Microsoft Teams" : "Call"),
              depends_on: "eval:doc.next_follow_up_date" },
            { fieldtype: "Section Break" },
            { fieldtype: "Data", fieldname: "next_action", label: __("Next step (becomes the title)"),
              depends_on: "eval:doc.next_follow_up_date" },
            { fieldtype: "Check", fieldname: "more_options", depends_on: "eval:doc.next_follow_up_date",
              label: __("Then open it to add attendees, a Teams / Zoom link or attachments") },
        ],
        primary_action_label: __("Save"),
        primary_action(v) {
            frappe.call({
                method: "alphax_crm.crm.followup.log_followup",
                args: {
                    reference_doctype: frm.doctype, reference_name: frm.docname,
                    channel: v.channel, meeting_type: v.meeting_type || "", direction: v.direction, outcome: v.outcome,
                    duration: v.duration || 0, summary: v.summary || "",
                    next_action: v.next_action || "", next_follow_up_date: v.next_follow_up_date || null,
                    next_follow_up_time: v.next_follow_up_time || null, next_follow_up_via: v.next_follow_up_via || null,
                    schedule: opts.schedule || null,
                },
                freeze: true, freeze_message: __("Saving..."),
                callback: (r) => {
                    d.hide();
                    frappe.show_alert({ message: v.next_follow_up_date ? __("Saved · next follow-up booked with reminders")
                        : __("Follow-up saved"), indicator: "green" });
                    const done = () => (opts.after ? opts.after(r.message) : window.alphax_refresh_followups(frm));
                    if (v.more_options && v.next_follow_up_date) {
                        frappe.db.get_value("AlphaX Follow-up", r.message, "next_schedule").then((x) => {
                            const name = x.message && x.message.next_schedule;
                            if (name) window.alphax_open_scheduler({ name, on_close: done });
                            else done();
                        });
                    } else done();
                },
            });
        },
    });
    d.show();
};

// "Log a Call" is a follow-up with channel Call (one history, one report, one reminder system).
window.alphax_log_call = function (frm) {
    window.alphax_log_followup(frm, { channel: "Call", call: true });
};

// Older entry points now lead to the Follow-ups panel, where history and calls are shown together.
window.alphax_followup_history = function (frm) { window.alphax_show_followups(frm); };
window.alphax_call_history = function (frm) { window.alphax_show_followups(frm); };
window.alphax_owner_banner = function () { /* the Lead Owner is shown in the Follow-ups panel header */ };

window.alphax_schedule_followup = function (frm, opts) {
    window.alphax_open_scheduler(Object.assign({
        reference_doctype: frm.doctype, reference_name: frm.docname || (frm.doc && frm.doc.name),
        on_close: () => window.alphax_refresh_followups(frm),
    }, opts || {}));
};

// The one Follow-up menu on Lead / Opportunity / PreLead.
window.alphax_followup_menu = function (frm) {
    if (frm.is_new()) return;
    const g = __("Follow-up");
    frm.add_custom_button(__("Schedule Follow-up"), () => window.alphax_schedule_followup(frm), g);
    frm.add_custom_button(__("Log Follow-up"), () => window.alphax_log_followup(frm), g);
    frm.add_custom_button(__("Log a Call"), () => window.alphax_log_call(frm), g);
    frm.add_custom_button(__("Show Follow-ups"), () => window.alphax_show_followups && window.alphax_show_followups(frm), g);
    if (typeof window.alphax_render_followups === "function") {
        try { window.alphax_render_followups(frm); } catch (e) { console.error("AlphaX CRM: follow-ups panel failed", e); }
    }
};
window.alphax_schedule_buttons = window.alphax_followup_menu;
