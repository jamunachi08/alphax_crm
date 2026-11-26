// AlphaX CRM — follow-up actions shared by Lead, Opportunity and PreLead (0.50.0).
// One way to record anything that happened (Log Follow-up; a call is a follow-up with channel Call) and one way
// to plan what happens next (the next date is booked as a scheduled follow-up with reminders). Everything shows
// in the Follow-ups panel on the record's Activities tab (alphax_followup_hub.js).

const AX_VIA = ["Call", "Microsoft Teams", "Zoom", "Google Meet", "Webex", "WhatsApp", "Email", "On-site Visit", "Other"];

// Two separate jobs:
//   Log Follow-up — emails, WhatsApp, meetings, visits, SMS … (no calls)
//   Log a Call    — calls only
// Both are saved as follow-ups (one history), and both can book or schedule the next step.
const AX_FOLLOWUP_CHANNELS = ["Email", "WhatsApp", "Meeting", "Visit", "SMS", "Other"];
const AX_FOLLOWUP_OUTCOMES = ["Completed", "Replied", "No Response", "Interested", "Not Interested", "Rescheduled", "Callback Requested"];
const AX_CALL_OUTCOMES = ["Connected", "No Answer", "Busy", "Left Voicemail", "Callback Requested", "Interested", "Not Interested"];

window.alphax_log_followup = function (frm, opts) {
    opts = opts || {};
    const call = !!opts.call;
    const channel = call ? "Call" : (AX_FOLLOWUP_CHANNELS.includes(opts.channel) ? opts.channel : "Email");
    const fields = call ? [
        { fieldtype: "Select", fieldname: "direction", label: __("Direction"), options: "Outgoing\nIncoming", default: "Outgoing" },
        { fieldtype: "Column Break" },
        { fieldtype: "Select", fieldname: "outcome", label: __("Outcome"), options: AX_CALL_OUTCOMES.join("\n"), default: "Connected", reqd: 1 },
        { fieldtype: "Column Break" },
        { fieldtype: "Duration", fieldname: "duration", label: __("Duration"), hide_days: 1 },
    ] : [
        { fieldtype: "Select", fieldname: "channel", label: __("Channel"), options: AX_FOLLOWUP_CHANNELS.join("\n"), default: channel, reqd: 1 },
        { fieldtype: "Select", fieldname: "meeting_type", label: __("Meeting Type"), options: "\nOnline Meeting\nOn-site Meeting",
          default: opts.meeting_type || "", depends_on: 'eval:doc.channel=="Meeting"', mandatory_depends_on: 'eval:doc.channel=="Meeting"' },
        { fieldtype: "Select", fieldname: "direction", label: __("Direction"), options: "Outgoing\nIncoming", default: "Outgoing" },
        { fieldtype: "Column Break" },
        { fieldtype: "Select", fieldname: "outcome", label: __("Outcome"), options: AX_FOLLOWUP_OUTCOMES.join("\n"),
          default: opts.schedule ? "Completed" : "Completed", reqd: 1 },
        { fieldtype: "Duration", fieldname: "duration", label: __("Duration"), hide_days: 1,
          depends_on: 'eval:["Meeting","Visit"].includes(doc.channel)' },
    ];
    fields.push(
        { fieldtype: "Section Break" },
        { fieldtype: "Small Text", fieldname: "summary", label: call ? __("What was discussed") : __("What happened"), reqd: 1 },
        { fieldtype: "Section Break", label: __("Next follow-up"),
          description: __("Pick a date to book the next step with reminders, or use Save & Schedule Follow-up for the full scheduler.") },
        { fieldtype: "Date", fieldname: "next_follow_up_date", label: __("Date") },
        { fieldtype: "Column Break" },
        { fieldtype: "Time", fieldname: "next_follow_up_time", label: __("At"), default: "10:00:00", depends_on: "eval:doc.next_follow_up_date" },
        { fieldtype: "Column Break" },
        { fieldtype: "Select", fieldname: "next_follow_up_via", label: __("Via"), options: AX_VIA.join("\n"),
          default: call ? "Call" : "Microsoft Teams", depends_on: "eval:doc.next_follow_up_date" },
        { fieldtype: "Section Break" },
        { fieldtype: "Data", fieldname: "next_action", label: __("Next step (becomes the title)"), depends_on: "eval:doc.next_follow_up_date" },
    );
    const d = new frappe.ui.Dialog({
        title: opts.title || (call ? __("Log a Call") : __("Log Follow-up")),
        fields,
        primary_action_label: __("Save"),
        primary_action: (v) => save(v, false),
    });
    // The full scheduler, straight from here: saves this follow-up first, then opens Schedule Follow-up for
    // the next step (the one just booked, or a new one if no date was picked).
    d.add_custom_action(__("Save & Schedule Follow-up"), () => {
        const v = d.get_values();
        if (v) save(v, true);
    }, "btn-default");

    function save(v, schedule_next) {
        frappe.call({
            method: "alphax_crm.crm.followup.log_followup",
            args: {
                reference_doctype: frm.doctype, reference_name: frm.docname,
                channel: call ? "Call" : v.channel, meeting_type: call ? "" : v.meeting_type || "",
                direction: v.direction, outcome: v.outcome, duration: v.duration || 0, summary: v.summary || "",
                next_action: v.next_action || "", next_follow_up_date: v.next_follow_up_date || null,
                next_follow_up_time: v.next_follow_up_time || null, next_follow_up_via: v.next_follow_up_via || null,
                schedule: opts.schedule || null,
            },
            freeze: true, freeze_message: __("Saving..."),
            callback: (r) => {
                d.hide();
                const name = r.message;
                frappe.show_alert({ message: v.next_follow_up_date ? __("Saved · next follow-up booked with reminders")
                    : (call ? __("Call saved") : __("Follow-up saved")), indicator: "green" });
                const done = () => (opts.after ? opts.after(name) : window.alphax_refresh_followups(frm));
                if (!schedule_next) return done();
                frappe.db.get_value("AlphaX Follow-up", name, "next_schedule").then((x) => {
                    const booked = x.message && x.message.next_schedule;
                    window.alphax_open_scheduler(booked ? { name: booked, on_close: done } : {
                        reference_doctype: frm.doctype, reference_name: frm.docname, source_follow_up: name,
                        start_date: v.next_follow_up_date || null, on_close: done,
                    });
                });
            },
        });
    }
    d.show();
};

// Outcome of a scheduled follow-up: a scheduled call is logged as a call, anything else as a follow-up.
window.alphax_log_outcome = function (ref, schedule, platform, title, after) {
    const target = { doctype: ref.doctype, docname: ref.name };
    const opts = { schedule, title: __("Log outcome · {0}", [title || schedule]), after };
    if (platform === "Call" || platform === "Phone Call") return window.alphax_log_call(target, opts);
    const online = ["Microsoft Teams", "Zoom", "Google Meet", "Webex"].includes(platform);
    window.alphax_log_followup(target, Object.assign(opts, {
        channel: platform === "WhatsApp" ? "WhatsApp" : platform === "Email" ? "Email" : platform === "On-site Visit" ? "Visit" : "Meeting",
        meeting_type: online ? "Online Meeting" : "On-site Meeting",
    }));
};

// "Log a Call" is a follow-up with channel Call (one history, one report, one reminder system).
window.alphax_log_call = function (frm, opts) {
    window.alphax_log_followup(frm, Object.assign({}, opts || {}, { call: true }));
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
    frm.add_custom_button(__("Log Follow-up"), () => window.alphax_log_followup(frm), g);
    frm.add_custom_button(__("Log a Call"), () => window.alphax_log_call(frm), g);
    frm.add_custom_button(__("Show Follow-ups"), () => window.alphax_show_followups && window.alphax_show_followups(frm), g);
    frm.add_custom_button(__("Schedule Follow-up"), () => window.alphax_schedule_followup(frm), g);
    if (typeof window.alphax_render_followups === "function") {
        try { window.alphax_render_followups(frm); } catch (e) { console.error("AlphaX CRM: follow-ups panel failed", e); }
    }
};
window.alphax_schedule_buttons = window.alphax_followup_menu;
