// AlphaX CRM — follow-up meeting reminders (crm/schedule.py).
// The server pushes "alphax_followup_reminder" when a reminder is due; reminders still open when the desk
// loads are fetched once. Each shows as a pop-up with Join / Open / Log outcome / Snooze / Dismiss, and as a
// browser notification when this tab is in the background and notifications are allowed.
(function () {
    const shown = new Set();
    const queue = [];
    let dialog = null;

    function starts_text(r) {
        const mins = moment(r.start).diff(moment(), "minutes");
        if (mins > 1440) return __("Starts {0}", [moment(r.start).fromNow()]);
        if (mins > 59) return __("Starts in {0} h {1} min", [Math.floor(mins / 60), mins % 60]);
        if (mins > 0) return __("Starts in {0} min", [mins]);
        if (moment().isBefore(moment(r.end))) return __("Started {0}", [moment(r.start).fromNow()]);
        return __("Ended");
    }

    function body(r) {
        const esc = frappe.utils.escape_html;
        const files = (r.attachments || []).map((f) =>
            `<a href="${encodeURI(f.file_url)}" target="_blank" style="margin-right:10px">${frappe.utils.icon("attachment", "xs")} ${esc(f.file_name || "")}</a>`).join("");
        return `<div style="border-left:4px solid #5b5fc7;padding:4px 0 4px 14px">
            <div style="font-size:16px;font-weight:600">${esc(r.subject)}</div>
            <div style="margin:4px 0"><b class="ax-starts">${starts_text(r)}</b> · ${esc(r.when)}${r.recurring ? " · " + __("repeating") : ""}</div>
            <div class="text-muted">${esc(__(r.platform || ""))}${r.location ? " · " + esc(r.location) : ""}</div>
            <div style="margin-top:6px">${__("Regarding")}: <a href="/app/${frappe.router.slug(r.reference_doctype)}/${encodeURIComponent(r.reference_name)}">
                ${esc(__(r.reference_doctype))} ${esc(r.reference_name)}</a> · ${esc(r.reference_title || "")}</div>
            <div class="text-muted" style="font-size:12px">${__("Organizer")}: ${esc(r.organizer || "-")}${r.lead_owner ? " · " + __("Lead Owner") + ": " + esc(r.lead_owner) : ""}</div>
            ${r.agenda ? `<div style="margin-top:8px;white-space:pre-wrap">${esc(r.agenda)}</div>` : ""}
            ${files ? `<div style="margin-top:8px">${files}</div>` : ""}
        </div>`;
    }

    function next() {
        if (dialog || !queue.length) return;
        const r = queue.shift();
        dialog = new frappe.ui.Dialog({
            title: __("Reminder"),
            fields: [
                { fieldtype: "HTML", fieldname: "body" },
                { fieldtype: "Section Break" },
                { fieldtype: "Select", fieldname: "snooze", label: __("Snooze for"),
                  options: [5, 10, 15, 30, 60].map((m) => ({ value: m, label: m < 60 ? __("{0} minutes", [m]) : __("1 hour") })), default: 5 },
                { fieldtype: "Column Break" },
                { fieldtype: "Button", fieldname: "snooze_btn", label: __("Snooze") },
            ],
            primary_action_label: r.meeting_link ? __("Join") : __("Open"),
            primary_action() {
                if (r.meeting_link) window.open(r.meeting_link, "_blank", "noopener");
                else frappe.set_route("alphax-schedule", r.schedule);
                close("dismiss_reminder", {});
            },
            secondary_action_label: __("Dismiss"),
            secondary_action() { close("dismiss_reminder", {}); },
        });
        dialog.fields_dict.body.$wrapper.html(body(r));
        dialog.fields_dict.snooze_btn.$input.on("click", () => close("snooze_reminder", { minutes: dialog.get_value("snooze") }));
        dialog.add_custom_action(__("Open meeting"), () => { frappe.set_route("alphax-schedule", r.schedule); close("dismiss_reminder", {}); });
        dialog.add_custom_action(__("Log outcome"), () => {
            const online = ["Microsoft Teams", "Zoom", "Google Meet", "Webex"].includes(r.platform);
            close("dismiss_reminder", {});
            window.alphax_log_followup({ doctype: r.reference_doctype, docname: r.reference_name, reload_doc() {} },
                { schedule: r.schedule, channel: "Meeting", meeting_type: online ? "Online Meeting" : "On-site Meeting",
                  title: __("Log Outcome · {0}", [r.subject]) });
        });
        const tick = setInterval(() => dialog && dialog.$wrapper.find(".ax-starts").text(starts_text(r)), 30000);
        dialog.onhide = () => {
            clearInterval(tick);
            if (!dialog._ax_handled) frappe.xcall("alphax_crm.crm.schedule.snooze_reminder", { name: r.name, minutes: 5 }).catch(() => {});
            dialog = null;
            setTimeout(next, 300);
        };
        function close(method, args) {
            dialog._ax_handled = true;
            frappe.xcall(`alphax_crm.crm.schedule.${method}`, Object.assign({ name: r.name }, args)).catch(() => {});
            dialog.hide();
        }
        dialog.show();
        try { frappe.utils.play_sound("alert"); } catch (e) { /* no sound */ }
        if (document.hidden && window.Notification && Notification.permission === "granted") {
            try {
                const n = new Notification(r.subject, { body: `${starts_text(r)} · ${r.when}`, tag: r.name });
                n.onclick = () => { window.focus(); n.close(); };
            } catch (e) { /* not supported */ }
        }
    }

    function show(r) {
        if (!r || !r.name || shown.has(r.name)) return;
        shown.add(r.name);
        queue.push(r);
        next();
    }

    function load_open() {
        if (window._ax_reminders_loaded || !frappe.session || frappe.session.user === "Guest") return;
        window._ax_reminders_loaded = true;
        frappe.realtime.on("alphax_followup_reminder", (r) => {
            shown.delete(r.name); // a snoozed reminder comes back with the same name
            show(r);
        });
        frappe.xcall("alphax_crm.crm.schedule.my_due_reminders").then((rows) => (rows || []).forEach(show)).catch(() => {});
        if (window.Notification && Notification.permission === "default") {
            // ask once, on the first click anywhere, so background tabs can alert too
            $(document).one("click", () => { try { Notification.requestPermission(); } catch (e) { /* ignore */ } });
        }
    }

    $(document).on("app_ready", load_open);
    $(document).ready(() => setTimeout(load_open, 4000));
})();
