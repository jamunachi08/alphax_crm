// AlphaX CRM — Follow-ups in one place (crm/followup_hub.py, crm/schedule.py). 0.50.0
//
//  • Follow-ups panel at the top of the record's "Follow-ups & Activities" tab (Lead, Opportunity, PreLead):
//    header (Lead Owner, next follow-up, last activity), Overdue, Coming up, History — with every action.
//    On a Lead it also shows follow-ups logged on that Lead's Opportunities and PreLead.
//  • Schedule Follow-up opens over the record (no page change), laid out like a Teams new-meeting form.
(function () {
    const HUB_FIELD = { "Lead": "alphax_followup_hub", "Opportunity": "alphax_followup_hub", "AlphaX PreLead": "followup_hub_html" };
    const ONLINE = ["Microsoft Teams", "Zoom", "Google Meet", "Webex"];
    const PLATFORMS = [
        ["Call", "#6b7280", "call"], ["Microsoft Teams", "#5b5fc7", "video"], ["Zoom", "#2d8cff", "video"],
        ["Google Meet", "#00897b", "video"], ["Webex", "#07c160", "video"], ["WhatsApp", "#25d366", "message"],
        ["Email", "#0ea5e9", "mail"], ["On-site Visit", "#b45309", "map-pin"], ["Other", "#6b7280", "dot-horizontal"],
    ];
    const CHANNEL_ICON = { Call: "📞", Email: "✉️", WhatsApp: "💬", Meeting: "🎥", Visit: "📍", SMS: "💬", Other: "•",
        "Microsoft Teams": "🎥", Zoom: "🎥", "Google Meet": "🎥", Webex: "🎥", "On-site Visit": "📍", "Phone Call": "📞" };
    const REPEAT = ["Does not repeat", "Daily", "Every working day", "Weekly", "Monthly"];
    const esc = (s) => frappe.utils.escape_html(s == null ? "" : String(s));
    const color_of = (p) => (PLATFORMS.find((x) => x[0] === p) || [p, "#6b7280"])[1];

    // ===================================================================== panel
    function hub_wrapper(frm) {
        const f = frm.fields_dict && frm.fields_dict[HUB_FIELD[frm.doctype]];
        return f ? f.$wrapper : null;
    }

    window.alphax_render_followups = function (frm) {
        const $w = hub_wrapper(frm);
        if (!$w || frm.is_new()) return;
        css();
        if (!$w.children().length) $w.html(`<div class="ax-hub"><div class="text-muted small">${__("Loading follow-ups…")}</div></div>`);
        frappe.call({ method: "alphax_crm.crm.followup_hub.hub", args: { reference_doctype: frm.doctype, reference_name: frm.doc.name } })
            .then((r) => paint(frm, $w, r.message || {}))
            .catch(() => $w.html(`<div class="ax-hub text-muted">${__("Follow-ups could not be loaded.")}</div>`));
    };

    window.alphax_refresh_followups = function (frm) {
        if (frm && frm.reload_doc && frm.doc) return frm.reload_doc();
        if (window.cur_frm && frm && cur_frm.doctype === frm.doctype && cur_frm.docname === frm.docname) cur_frm.reload_doc();
    };

    window.alphax_show_followups = function (frm) {
        const field = HUB_FIELD[frm.doctype];
        if (frm.fields_dict[field]) frm.scroll_to_field(field);
    };

    function paint(frm, $w, h) {
        const writable = h.can_write && !(frm.doctype === "AlphaX PreLead" && frm.doc.converted);
        const head = [
            h.owner_name ? `${__("Lead Owner")}: <b>${esc(h.owner_name)}</b>` : "",
            h.next_date ? `${__("Next follow-up")}: <b>${esc(frappe.datetime.str_to_user(h.next_date))}</b>` : `<span class="ax-warn">${__("No next follow-up")}</span>`,
            h.last_activity ? `${__("Last activity")}: ${esc(h.last_activity_type || "")} · ${esc(frappe.datetime.comment_when(h.last_activity))}${h.last_activity_by ? " · " + esc(h.last_activity_by) : ""}` : "",
        ].filter(Boolean).join('<span class="ax-dot">·</span>');
        const lead_note = frm.doctype !== "Lead" && h.lead
            ? `<div class="ax-note">${__("Everything here also shows on Lead")} <a href="/app/lead/${encodeURIComponent(h.lead)}">${esc(h.lead)}</a>.</div>` : "";
        const card = (s, overdue) => `<div class="ax-meet ${overdue ? "overdue" : ""}" style="--c:${color_of(s.platform)}">
            <div class="ax-meet-main">
              <div class="ax-meet-when">${esc(s.when)}${s.recurring ? ` · <span class="text-muted">${__("repeats")}</span>` : ""}</div>
              <div class="ax-meet-title">${CHANNEL_ICON[s.platform] || "•"} <b>${esc(s.subject)}</b> <span class="text-muted">· ${esc(__(s.platform))}</span>
                ${s.files ? ` · 📎${s.files}` : ""}${s.elsewhere ? ` · <span class="text-muted">${esc(__(s.reference_doctype))} ${esc(s.reference_name)}</span>` : ""}</div>
              ${s.organizer_name ? `<div class="text-muted small">${__("Organizer")}: ${esc(s.organizer_name)}</div>` : ""}
            </div>
            <div class="ax-meet-actions">
              ${s.meeting_link ? `<button class="btn btn-xs btn-primary" data-join="${esc(s.meeting_link)}">${__("Join")}</button>` : ""}
              <button class="btn btn-xs btn-default" data-open="${esc(s.name)}">${__("Open")}</button>
              ${writable ? `<button class="btn btn-xs btn-default" data-outcome="${esc(s.name)}" data-platform="${esc(s.platform)}"
                  data-ref="${esc(s.reference_doctype)}|${esc(s.reference_name)}" data-title="${esc(s.subject)}">${__("Log outcome")}</button>` : ""}
            </div></div>`;
        const kinds = { followup: "", call: "", cancelled: "ax-muted" };
        const item = (x) => {
            const when = x.at ? frappe.datetime.str_to_user(x.at) : "";
            const ch = x.channel === "Meeting" && x.meeting_type ? `${x.channel} · ${x.meeting_type}` : x.channel;
            const dur = x.duration ? ` · ${Math.round(x.duration / 60)} ${__("min")}` : "";
            const next = x.next_date ? `<div class="ax-next">→ ${__("Next")}: ${esc(frappe.datetime.str_to_user(x.next_date))}${x.next_action ? " · " + esc(x.next_action) : ""}${x.next_schedule ? ` · <a data-open="${esc(x.next_schedule)}">${__("booked")}</a>` : ""}</div>` : "";
            const label = x.kind === "cancelled" ? `${esc(__(ch))} · ${__("cancelled")}` : `${esc(__(ch))}${x.direction ? " (" + esc(__(x.direction)) + ")" : ""}${x.outcome ? " · " + esc(__(x.outcome)) : ""}${dur}`;
            return `<div class="ax-item ${kinds[x.kind] || ""}" data-channel="${esc(x.channel)}">
                <div class="ax-item-icon">${CHANNEL_ICON[x.channel] || "•"}</div>
                <div class="ax-item-body"><div><b>${label}</b> <span class="text-muted">· ${esc(when)}${x.by ? " · " + esc(x.by) : ""}${x.elsewhere ? " · " + esc(x.record) : ""}</span></div>
                ${x.summary ? `<div class="ax-sum">${esc(x.summary)}</div>` : ""}${next}</div></div>`;
        };
        const chans = [...new Set((h.history || []).map((x) => x.channel).filter(Boolean))];
        $w.html(`<div class="ax-hub">
            <div class="ax-hub-top">
              <div><div class="ax-hub-title">${__("Follow-ups")}</div><div class="ax-hub-head">${head}</div>${lead_note}</div>
              ${writable ? `<div class="ax-hub-btns">
                <button class="btn btn-sm btn-primary" data-act="schedule">+ ${__("Schedule")}</button>
                <button class="btn btn-sm btn-default" data-act="log">${__("Log follow-up")}</button>
                <button class="btn btn-sm btn-default" data-act="call">📞 ${__("Log a call")}</button></div>` : ""}
            </div>
            ${(h.overdue || []).length ? `<div class="ax-sec ax-sec-warn">${__("Overdue — log the outcome or reschedule")} (${h.overdue.length})</div>${h.overdue.map((s) => card(s, true)).join("")}` : ""}
            <div class="ax-sec">${__("Coming up")} (${(h.upcoming || []).length})</div>
            ${(h.upcoming || []).map((s) => card(s)).join("") || `<div class="ax-empty">${__("Nothing scheduled.")}${writable ? ` <a data-act="schedule">${__("Schedule the next follow-up")}</a>` : ""}</div>`}
            <div class="ax-sec ax-sec-row"><span>${__("History")} (${(h.history || []).length})</span>
              ${chans.length > 1 ? `<span class="ax-filters"><a class="active" data-filter="">${__("All")}</a>${chans.map((c) => `<a data-filter="${esc(c)}">${esc(__(c))}</a>`).join("")}</span>` : ""}</div>
            <div class="ax-history">${(h.history || []).map(item).join("") || `<div class="ax-empty">${__("No follow-ups yet.")}</div>`}</div>
            <div class="ax-hub-foot"><a data-act="calendar">${__("Follow-up calendar")}</a></div>
        </div>`);
        const $h = $w.find(".ax-history");
        if ($h.children(".ax-item").length > 8) {
            $h.children(".ax-item").slice(8).addClass("ax-hidden");
            $h.after(`<a class="ax-more">${__("Show all {0}", [$h.children(".ax-item").length])}</a>`);
        }
        $w.off("click.ax").on("click.ax", "[data-act]", function () {
            const act = $(this).attr("data-act");
            if (act === "schedule") window.alphax_schedule_followup(frm);
            if (act === "log") window.alphax_log_followup(frm);
            if (act === "call") window.alphax_log_call(frm);
            if (act === "calendar") frappe.set_route("List", "AlphaX Follow-up Schedule", "Calendar", "default");
        }).on("click.ax", "[data-join]", function () {
            window.open($(this).attr("data-join"), "_blank", "noopener");
        }).on("click.ax", "[data-open]", function () {
            window.alphax_open_scheduler({ name: $(this).attr("data-open"), on_close: () => window.alphax_refresh_followups(frm) });
        }).on("click.ax", "[data-outcome]", function () {
            const [dt, dn] = $(this).attr("data-ref").split("|");
            window.alphax_log_followup({ doctype: dt, docname: dn }, {
                schedule: $(this).attr("data-outcome"), channel: "Meeting",
                meeting_type: ONLINE.includes($(this).attr("data-platform")) ? "Online Meeting" : "On-site Meeting",
                title: __("Log outcome · {0}", [$(this).attr("data-title")]), after: () => window.alphax_refresh_followups(frm),
            });
        }).on("click.ax", "[data-filter]", function () {
            const f = $(this).attr("data-filter");
            $(this).addClass("active").siblings().removeClass("active");
            $w.find(".ax-item").each(function () { $(this).toggle(!f || $(this).attr("data-channel") === f); });
            $w.find(".ax-more").remove();
        }).on("click.ax", ".ax-more", function () {
            $w.find(".ax-hidden").removeClass("ax-hidden");
            $(this).remove();
        });
    }

    // ===================================================================== scheduler dialog
    window.alphax_open_scheduler = function (opts) {
        opts = opts || {};
        frappe.call({
            method: "alphax_crm.crm.schedule.get_schedule_context",
            args: { reference_doctype: opts.reference_doctype, reference_name: opts.reference_name, name: opts.name },
            freeze: true,
        }).then((r) => new Scheduler(opts, r.message || {}));
    };

    class Scheduler {
        constructor(opts, ctx) {
            css();
            this.opts = opts;
            this.ctx = ctx;
            const doc = ctx.doc;
            const ref = ctx.reference || {};
            this.state = { name: doc ? doc.name : null, status: doc ? doc.status : "Scheduled",
                can_write: doc ? doc.can_write : true, repeat_open: !!(doc && doc.repeat && doc.repeat !== "Does not repeat") };
            this.saved = false;
            this.d = new frappe.ui.Dialog({
                title: doc ? `${esc(doc.subject)} · ${esc(__(this.state.status))}` : __("Schedule Follow-up · {0}", [esc(ref.title || ref.name || "")]),
                size: "extra-large",
                fields: [{ fieldtype: "HTML", fieldname: "body" }],
                primary_action_label: __("Save"),
                primary_action: () => this.save(),
                secondary_action_label: __("Close"),
                secondary_action: () => this.d.hide(),
            });
            this.d.onhide = () => { if (this.opts.on_close) this.opts.on_close(this.saved); };
            this.$body = $(`<div class="ax-sched"></div>`).appendTo(this.d.fields_dict.body.$wrapper);
            this.render();
            if (this.state.name && this.state.can_write) {
                this.d.add_custom_action(__("Log outcome"), () => this.log_outcome(), "btn-default");
                if (this.state.status === "Scheduled") this.d.add_custom_action(__("Cancel follow-up"), () => this.cancel(), "btn-default");
                this.d.add_custom_action(__("Open form"), () => { this.d.hide(); frappe.set_route("Form", "AlphaX Follow-up Schedule", this.state.name); }, "btn-default");
            }
            this.d.show();
        }

        $(key) { return this.$body.find(`[data-ax="${key}"]`); }

        control(key, df) {
            const parent = this.$body.find(`[data-ax-control="${key}"]`);
            const c = frappe.ui.form.make_control({ parent, df: Object.assign({ fieldname: key, label: "" }, df), render_input: true,
                only_input: df.fieldtype === "Date" });
            c.refresh();
            return c;
        }

        render() {
            const ctx = this.ctx, doc = ctx.doc, d = ctx.defaults || {}, ref = ctx.reference || {};
            const start = doc ? moment(doc.start_local) : (() => {
                if (this.opts.start_date) return moment(this.opts.start_date + " 10:00:00");
                const m = moment().add(30, "minutes");
                return m.minutes(m.minutes() < 30 ? 30 : 60).seconds(0);
            })();
            const end = doc ? moment(doc.end_local) : start.clone().add(d.duration || 30, "minutes");
            this.tz = doc ? doc.display_tz : ctx.system_tz;
            const row = (icon, label, body, cls = "") => `<div class="ax-row ${cls}"><div class="ax-label">${frappe.utils.icon(icon, "sm")}<span>${label}</span></div><div class="ax-field">${body}</div></div>`;
            this.$body.html(`
              ${row("file", __("Regarding"), `<a href="/app/${frappe.router.slug(ref.doctype || "")}/${encodeURIComponent(ref.name || "")}">${esc(__(ref.doctype || ""))} ${esc(ref.name || "")}</a>
                  · <b>${esc(ref.title || "")}</b>${ref.lead_owner ? ` · ${__("Lead Owner")}: ${esc(ref.lead_owner_name || ref.lead_owner)}` : ""}`)}
              ${row("edit", __("Title"), `<input data-ax="title" class="ax-title" maxlength="140" placeholder="${__("Add a title")}">`)}
              ${row("video", __("Via"), `<div class="ax-platforms" data-ax="platforms"></div>`)}
              ${row("calendar", __("Start time"), `<div class="ax-when"><div class="ax-date" data-ax-control="start_date"></div>
                  <select data-ax="start_time" class="ax-select ax-time"></select>
                  <label class="ax-check"><input type="checkbox" data-ax="all_day"> ${__("All day")}</label>
                  <label class="ax-check"><input type="checkbox" data-ax="tz_on"> ${frappe.utils.icon("globe", "sm")} ${__("Time zones")}</label></div>`)}
              ${row("calendar", __("End time"), `<div class="ax-when"><div class="ax-date" data-ax-control="end_date"></div>
                  <select data-ax="end_time" class="ax-select ax-time"></select><span class="ax-duration" data-ax="duration"></span>
                  <a class="ax-link" data-ax="make_recurring">${frappe.utils.icon("refresh", "sm")} ${__("Make recurring")}</a></div>`)}
              ${row("globe", __("Time zone"), `<select data-ax="tz" class="ax-select ax-wide"></select><div class="ax-hint" data-ax="tz_hint"></div>`, "ax-tz-row")}
              ${row("refresh", __("Repeat"), `<div class="ax-when"><select data-ax="repeat" class="ax-select"></select>
                  <span class="ax-every">${__("every")} <input type="number" min="1" max="30" data-ax="repeat_every" class="ax-input ax-num"> <span data-ax="repeat_unit"></span></span>
                  <span>${__("until")}</span><div class="ax-date" data-ax-control="repeat_until"></div>
                  <a class="ax-link" data-ax="remove_repeat">${__("Remove")}</a></div><div class="ax-hint" data-ax="repeat_hint"></div>`, "ax-repeat-row")}
              ${row("link", __("Meeting link"), `<div class="ax-when"><input data-ax="meeting_link" class="ax-input ax-wide" placeholder="${__("Paste the Teams / Zoom / Meet link")}">
                  <button class="btn btn-default btn-xs" data-ax="join_test">${__("Open")}</button></div>`, "ax-link-row")}
              ${row("map-pin", __("Location"), `<input data-ax="location" class="ax-input ax-wide" placeholder="${__("Add a location")}">`, "ax-loc-row")}
              ${row("users", __("Attendees"), `<div data-ax-control="internal"></div>`)}
              ${row("mail", __("Client emails"), `<div data-ax="external_chips"></div><input data-ax="external_input" class="ax-input ax-wide" placeholder="${__("Add emails (Enter or comma)")}"><div data-ax="external_suggest"></div>`)}
              ${row("notification", __("Reminders"), `<div data-ax="reminders"></div><a class="ax-link" data-ax="add_reminder">+ ${__("Add reminder")}</a>
                  <div class="ax-hint">${__("Pop-up in the ERP and/or email — to you, the Lead Owner and internal attendees.")}</div>`)}
              ${row("attachment", __("Attachments"), `<div data-ax="attachments"></div><button class="btn btn-default btn-xs" data-ax="attach">${frappe.utils.icon("upload", "xs")} ${__("Attach file")}</button>`)}
              ${row("mail", __("Invitation"), `<label class="ax-check"><input type="checkbox" data-ax="send_invitation"> ${__("Email the calendar invitation (.ics) with the attachments to the attendees")}</label>
                  <div class="ax-hint" data-ax="invite_hint"></div>`)}
              ${row("list", __("Details"), `<div data-ax-control="agenda" class="ax-agenda"></div>`)}`);
            this.$("title").val(doc ? doc.subject : "");
            this.platform = doc ? (doc.platform === "Phone Call" ? "Call" : doc.platform) : d.platform;
            this.paint_platforms();
            this.start_date = this.control("start_date", { fieldtype: "Date" });
            this.end_date = this.control("end_date", { fieldtype: "Date" });
            this.start_date.set_value(start.format("YYYY-MM-DD"));
            this.end_date.set_value(end.format("YYYY-MM-DD"));
            this.times(this.$("start_time"), start.format("HH:mm:ss"));
            this.times(this.$("end_time"), end.format("HH:mm:ss"));
            this.$("all_day").prop("checked", !!(doc && doc.all_day));
            this.$("tz_on").prop("checked", this.tz !== ctx.system_tz);
            let zones = [];
            try { zones = Intl.supportedValuesOf("timeZone"); } catch (e) { zones = [ctx.system_tz, "UTC"]; }
            if (!zones.includes(ctx.system_tz)) zones.unshift(ctx.system_tz);
            this.$("tz").html(zones.map((z) => `<option value="${z}">${z.replace(/_/g, " ")}${z === ctx.system_tz ? " (" + __("system") + ")" : ""}</option>`).join("")).val(this.tz);
            this.$("repeat").html(REPEAT.map((x) => `<option value="${x}">${__(x)}</option>`).join("")).val(doc && doc.repeat && doc.repeat !== "Does not repeat" ? doc.repeat : "Weekly");
            this.$("repeat_every").val(doc ? doc.repeat_every || 1 : 1);
            this.repeat_until = this.control("repeat_until", { fieldtype: "Date" });
            if (doc && doc.repeat_until) this.repeat_until.set_value(doc.repeat_until);
            this.$("meeting_link").val(doc ? doc.meeting_link || "" : "");
            this.$("location").val(doc ? doc.location || "" : "");
            this.internal = this.control("internal", { fieldtype: "MultiSelectPills", placeholder: __("Add colleagues"),
                get_data: (txt) => frappe.db.get_link_options("User", txt, { user_type: "System User", enabled: 1 }) });
            this.internal.set_value(doc ? (doc.attendees || []).filter((a) => a.attendee_type === "Internal").map((a) => a.user) : []);
            this.external = doc ? (doc.attendees || []).filter((a) => a.attendee_type === "External").map((a) => a.email) : [];
            this.paint_external();
            this.reminders = doc ? (doc.reminders || []).filter((x) => x.popup || x.email).map((x) => ({ remind_before: x.remind_before, popup: x.popup, email: x.email }))
                : (d.reminders || []).map((x) => Object.assign({}, x));
            this.paint_reminders();
            this.$("send_invitation").prop("checked", doc ? !!doc.send_invitation : !!d.send_invitation);
            this.agenda = this.control("agenda", { fieldtype: "Text Editor", placeholder: __("Agenda, notes for attendees") });
            this.agenda.set_value(doc ? doc.agenda || "" : "");
            this.paint_files(ctx.attachments || []);
            this.bind();
            this.sync();
            if (!this.state.can_write) { this.$body.find("input,select,textarea,button").prop("disabled", true); this.d.get_primary_btn().hide(); }
        }

        times($sel, value) {
            const opts = [];
            for (let m = 0; m < 1440; m += 15) {
                const t = moment().startOf("day").add(m, "minutes");
                opts.push([t.format("HH:mm:00"), t.format("h:mm A")]);
            }
            if (value && !opts.find((o) => o[0] === value)) opts.push([value, moment(value, "HH:mm:ss").format("h:mm A")]);
            opts.sort((a, b) => a[0].localeCompare(b[0]));
            $sel.html(opts.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")).val(value);
        }

        start_m() { return moment(`${this.start_date.get_value()} ${this.$("start_time").val() || "00:00:00"}`); }
        end_m() { return moment(`${this.end_date.get_value()} ${this.$("end_time").val() || "00:00:00"}`); }

        paint_platforms() {
            this.$("platforms").html(PLATFORMS.map(([n, c, i]) => `<button class="ax-chip ${n === this.platform ? "active" : ""}" data-platform="${n}" style="--c:${c}">${frappe.utils.icon(i, "xs")} ${__(n)}</button>`).join(""));
        }

        paint_external() {
            const ref = this.ctx.reference || {};
            this.$("external_chips").html(this.external.map((e, i) => `<span class="ax-pill">${esc(e)} <a data-remove-ext="${i}">×</a></span>`).join(""));
            this.$("external_suggest").html(ref.email && !this.external.includes(ref.email) ? `<a class="ax-link" data-add-ext="${esc(ref.email)}">+ ${__("Add {0}", [esc(ref.email)])}</a>` : "");
        }

        add_external(value) {
            (value || "").split(/[,;\s]+/).map((v) => v.trim()).filter(Boolean).forEach((e) => {
                if (!frappe.utils.validate_type(e, "email")) return frappe.show_alert({ message: __("{0} is not a valid email", [esc(e)]), indicator: "orange" });
                if (!this.external.includes(e)) this.external.push(e);
            });
            this.paint_external();
        }

        paint_reminders() {
            const opts = this.ctx.reminder_options || [];
            this.$("reminders").html(this.reminders.map((r, i) => `<div class="ax-reminder" data-i="${i}">
                <select class="ax-select" data-r="remind_before">${opts.map((o) => `<option value="${o}" ${o === r.remind_before ? "selected" : ""}>${__(o)}</option>`).join("")}</select>
                <label class="ax-check"><input type="checkbox" data-r="popup" ${r.popup ? "checked" : ""}> ${__("Pop-up")}</label>
                <label class="ax-check"><input type="checkbox" data-r="email" ${r.email ? "checked" : ""}> ${__("Email")}</label>
                <a class="ax-link" data-r="remove">${frappe.utils.icon("delete", "xs")}</a></div>`).join("") || `<div class="ax-hint">${__("No reminders")}</div>`);
        }

        paint_files(files) {
            this.$("attachments").html((files || []).map((f) => `<div>${frappe.utils.icon("file", "xs")} <a href="${encodeURI(f.file_url)}" target="_blank">${esc(f.file_name || f.file_url)}</a></div>`).join("")
                || `<div class="ax-hint">${__("No attachments")}</div>`);
        }

        sync() {
            const all_day = this.$("all_day").is(":checked");
            this.$("start_time").add(this.$("end_time")).toggle(!all_day);
            this.$body.find(".ax-tz-row").toggle(this.$("tz_on").is(":checked"));
            this.$body.find(".ax-repeat-row").toggle(this.state.repeat_open);
            this.$("make_recurring").toggle(!this.state.repeat_open);
            const rep = this.$("repeat").val();
            this.$body.find(".ax-every").toggle(rep !== "Every working day");
            this.$("repeat_unit").text({ Daily: __("day(s)"), Weekly: __("week(s)"), Monthly: __("month(s)") }[rep] || "");
            this.$("repeat_hint").text(rep === "Every working day" ? __("Uses the working days in AlphaX CRM Settings.") : "");
            const online = ONLINE.includes(this.platform);
            this.$body.find(".ax-link-row").toggle(online || !!this.$("meeting_link").val());
            this.$body.find(".ax-loc-row").toggle(this.platform === "On-site Visit" || this.platform === "Other" || !!this.$("location").val());
            const mins = this.end_m().diff(this.start_m(), "minutes");
            this.$("duration").text(all_day ? "" : mins > 0 ? (mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60 ? (mins % 60) + "m" : ""}` : `${mins}m`) : __("ends before it starts")).toggleClass("ax-bad", !all_day && mins <= 0);
            const tz = this.$("tz").val();
            this.$("tz_hint").text(tz && tz !== this.ctx.system_tz ? __("Times above are in {0}; reminders follow {1} time.", [tz, this.ctx.system_tz]) : "");
            const sent = this.ctx.doc && this.ctx.doc.invitation_sent_on;
            this.$("invite_hint").text(sent ? __("Last sent {0}. Sent again when the time or link changes.", [frappe.datetime.comment_when(sent)])
                : __("Colleagues also get the ERP link; clients get a clean invitation."));
            this.d.set_primary_action(this.$("send_invitation").is(":checked") ? __("Save & Send") : __("Save"), () => this.save());
        }

        bind() {
            const me = this;
            let last = this.start_m();
            const keep = () => {
                const dur = this.end_m().diff(last, "minutes");
                const s = this.start_m();
                if (dur > 0) {
                    const e = s.clone().add(dur, "minutes");
                    this.end_date.set_value(e.format("YYYY-MM-DD"));
                    this.times(this.$("end_time"), e.format("HH:mm:00"));
                }
                last = s;
                this.sync();
            };
            this.start_date.$input.on("change", () => setTimeout(keep, 50));
            this.$("start_time").on("change", keep);
            this.end_date.$input.on("change", () => setTimeout(() => this.sync(), 50));
            this.$body.on("change", '[data-ax="end_time"],[data-ax="all_day"],[data-ax="tz_on"],[data-ax="tz"],[data-ax="repeat"],[data-ax="send_invitation"]', () => this.sync());
            this.$body.on("input", '[data-ax="meeting_link"],[data-ax="location"]', () => this.sync());
            this.$("make_recurring").on("click", () => { this.state.repeat_open = true; this.sync(); });
            this.$("remove_repeat").on("click", () => { this.state.repeat_open = false; this.sync(); });
            this.$("platforms").on("click", "[data-platform]", function () { me.platform = $(this).attr("data-platform"); me.paint_platforms(); me.sync(); });
            this.$("join_test").on("click", () => {
                const url = (this.$("meeting_link").val() || "").trim();
                if (url) window.open(/^https?:\/\//i.test(url) ? url : "https://" + url, "_blank", "noopener");
            });
            this.$("external_input").on("keydown", function (e) {
                if (e.key === "Enter" || e.key === ",") { e.preventDefault(); me.add_external(this.value); this.value = ""; }
            }).on("blur", function () { if (this.value) { me.add_external(this.value); this.value = ""; } });
            this.$body.on("click", "[data-remove-ext]", function () { me.external.splice(+$(this).attr("data-remove-ext"), 1); me.paint_external(); });
            this.$body.on("click", "[data-add-ext]", function () { me.add_external($(this).attr("data-add-ext")); });
            this.$("add_reminder").on("click", () => { this.reminders.push({ remind_before: "15 minutes before", popup: 1, email: 1 }); this.paint_reminders(); });
            this.$("reminders").on("change", "[data-r]", function () {
                const i = +$(this).closest(".ax-reminder").attr("data-i");
                me.reminders[i][$(this).attr("data-r")] = this.type === "checkbox" ? (this.checked ? 1 : 0) : this.value;
            }).on("click", '[data-r="remove"]', function () { me.reminders.splice(+$(this).closest(".ax-reminder").attr("data-i"), 1); me.paint_reminders(); });
            this.$("attach").on("click", () => this.attach());
        }

        collect() {
            const all_day = this.$("all_day").is(":checked");
            const s = this.start_m(), e = this.end_m();
            if (!this.start_date.get_value()) frappe.throw(__("Pick a start date."));
            if (!all_day && e.diff(s, "minutes") <= 0) frappe.throw(__("It ends before it starts."));
            const ref = this.ctx.reference || {};
            return {
                name: this.state.name, reference_doctype: ref.doctype, reference_name: ref.name,
                source_follow_up: this.opts.source_follow_up || null,
                subject: this.$("title").val(), platform: this.platform, all_day: all_day ? 1 : 0,
                time_zone: this.$("tz_on").is(":checked") ? this.$("tz").val() : this.ctx.system_tz,
                start: s.format("YYYY-MM-DD HH:mm:ss"), end: (all_day ? moment(`${this.end_date.get_value()} 23:59:59`) : e).format("YYYY-MM-DD HH:mm:ss"),
                repeat: this.state.repeat_open ? this.$("repeat").val() : "Does not repeat",
                repeat_every: this.$("repeat_every").val() || 1, repeat_until: this.state.repeat_open ? this.repeat_until.get_value() || null : null,
                meeting_link: this.$("meeting_link").val(), location: this.$("location").val(),
                internal: this.internal.get_value() || [], external: this.external, reminders: this.reminders,
                agenda: this.agenda.get_value() || "", send_invitation: this.$("send_invitation").is(":checked") ? 1 : 0,
            };
        }

        save(after) {
            const data = this.collect();
            return frappe.call({ method: "alphax_crm.crm.schedule.save_schedule", args: { data }, freeze: true,
                freeze_message: data.send_invitation ? __("Saving and sending the invitation…") : __("Saving…") }).then((r) => {
                this.saved = true;
                this.state.name = r.message && r.message.name;
                frappe.show_alert({ message: __("Follow-up scheduled · reminders set"), indicator: "green" });
                if (after) return after(this.state.name);
                this.d.hide();
            });
        }

        attach() {
            const go = (name) => new frappe.ui.FileUploader({
                doctype: "AlphaX Follow-up Schedule", docname: name, folder: "Home/Attachments",
                on_success: () => frappe.call({ method: "alphax_crm.crm.schedule.get_schedule_context", args: { name } })
                    .then((r) => { this.ctx.attachments = r.message.attachments; this.paint_files(r.message.attachments); }),
            });
            if (this.state.name) return go(this.state.name);
            frappe.confirm(__("It is saved first so files can be attached. Continue?"), () => this.save((name) => go(name)));
        }

        log_outcome() {
            const ref = this.ctx.reference || {};
            const name = this.state.name;
            this.d.hide();
            window.alphax_log_followup({ doctype: ref.doctype, docname: ref.name }, {
                schedule: name, channel: "Meeting", meeting_type: ONLINE.includes(this.platform) ? "Online Meeting" : "On-site Meeting",
                title: __("Log outcome · {0}", [this.$("title").val() || name]), after: () => this.opts.on_close && this.opts.on_close(true),
            });
        }

        cancel() {
            const sent = this.ctx.doc && this.ctx.doc.invitation_sent_on;
            frappe.confirm(sent ? __("Cancel this follow-up? Attendees who got the invitation are sent a cancellation.") : __("Cancel this follow-up?"), () =>
                frappe.call({ method: "alphax_crm.crm.schedule.cancel_schedule", args: { name: this.state.name }, freeze: true }).then(() => {
                    this.saved = true;
                    frappe.show_alert({ message: __("Follow-up cancelled"), indicator: "orange" });
                    this.d.hide();
                }));
        }
    }

    // ===================================================================== styles
    function css() {
        if (document.getElementById("ax-hub-css")) return;
        $(`<style id="ax-hub-css">
        .ax-hub { border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; margin-bottom: 16px; background: var(--card-bg); }
        .ax-hub-top { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: flex-start; }
        .ax-hub-title { font-size: 16px; font-weight: 600; }
        .ax-hub-head { color: var(--text-muted); font-size: 12px; margin-top: 2px; }
        .ax-hub .ax-dot { margin: 0 6px; }
        .ax-hub .ax-warn { color: var(--orange-600); font-weight: 600; }
        .ax-hub .ax-note { font-size: 12px; margin-top: 4px; }
        .ax-hub-btns { display: flex; gap: 6px; flex-wrap: wrap; }
        .ax-hub .ax-sec { margin: 14px 0 6px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); }
        .ax-hub .ax-sec-warn { color: var(--orange-600); }
        .ax-hub .ax-sec-row { display: flex; justify-content: space-between; align-items: center; }
        .ax-hub .ax-filters a { margin-left: 10px; text-transform: none; font-weight: normal; cursor: pointer; }
        .ax-hub .ax-filters a.active { color: var(--text-color); font-weight: 600; text-decoration: underline; }
        .ax-hub .ax-meet { display: flex; justify-content: space-between; gap: 10px; align-items: center; border-left: 4px solid var(--c); background: var(--subtle-fg); border-radius: 6px; padding: 8px 12px; margin-bottom: 6px; flex-wrap: wrap; }
        .ax-hub .ax-meet.overdue { background: var(--bg-orange, #fff7ed); }
        .ax-hub .ax-meet-when { font-size: 12px; font-weight: 600; }
        .ax-hub .ax-meet-actions { display: flex; gap: 6px; }
        .ax-hub .ax-item { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border-color); }
        .ax-hub .ax-item:last-child { border-bottom: none; }
        .ax-hub .ax-item.ax-muted { opacity: .6; }
        .ax-hub .ax-item-icon { width: 22px; text-align: center; }
        .ax-hub .ax-sum { white-space: pre-wrap; margin-top: 2px; }
        .ax-hub .ax-next { color: var(--purple-600, #6d28d9); font-size: 12px; margin-top: 2px; }
        .ax-hub .ax-next a, .ax-hub .ax-empty a, .ax-hub .ax-more, .ax-hub-foot a { cursor: pointer; }
        .ax-hub .ax-hidden { display: none; }
        .ax-hub .ax-empty { color: var(--text-muted); font-size: 13px; padding: 4px 0; }
        .ax-hub-foot { margin-top: 10px; font-size: 12px; }
        .ax-sched .ax-row { display: grid; grid-template-columns: 140px 1fr; gap: 12px; align-items: center; padding: 8px 4px; border-bottom: 1px solid var(--border-color); }
        .ax-sched .ax-row:last-child { border-bottom: none; }
        .ax-sched .ax-label { color: var(--text-muted); display: flex; gap: 8px; align-items: center; font-size: 13px; }
        .ax-sched .ax-title { width: 100%; border: none; border-bottom: 2px solid var(--border-color); font-size: 18px; padding: 4px 0; background: transparent; outline: none; }
        .ax-sched .ax-title:focus { border-bottom-color: #5b5fc7; }
        .ax-sched .ax-when { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .ax-sched .ax-date { width: 150px; }
        .ax-sched .ax-select, .ax-sched .ax-input { height: 32px; border: 1px solid var(--border-color); border-radius: 4px; padding: 0 8px; background: var(--control-bg); }
        .ax-sched .ax-time { width: 115px; }
        .ax-sched .ax-wide { width: 100%; max-width: 520px; }
        .ax-sched .ax-num { width: 58px; }
        .ax-sched .ax-check { display: inline-flex; gap: 6px; align-items: center; margin: 0; font-weight: normal; cursor: pointer; }
        .ax-sched .ax-link { color: #5b5fc7; cursor: pointer; display: inline-flex; gap: 4px; align-items: center; }
        .ax-sched .ax-hint, .ax-sched .ax-duration { color: var(--text-muted); font-size: 12px; }
        .ax-sched .ax-bad { color: var(--red-500); }
        .ax-sched .ax-platforms { display: flex; flex-wrap: wrap; gap: 6px; }
        .ax-sched .ax-chip { border: 1px solid var(--border-color); background: var(--card-bg); border-radius: 16px; padding: 3px 11px; font-size: 12px; display: inline-flex; gap: 5px; align-items: center; }
        .ax-sched .ax-chip.active { border-color: var(--c); background: var(--c); color: #fff; }
        .ax-sched .ax-chip.active .icon { stroke: #fff; }
        .ax-sched .ax-pill { display: inline-flex; gap: 6px; background: var(--subtle-fg); border-radius: 12px; padding: 2px 10px; margin: 0 6px 6px 0; font-size: 12px; }
        .ax-sched .ax-pill a { cursor: pointer; }
        .ax-sched .ax-reminder { display: flex; gap: 12px; align-items: center; margin-bottom: 6px; }
        .ax-sched .ax-agenda .ql-editor { min-height: 120px; }
        @media (max-width: 720px) { .ax-sched .ax-row { grid-template-columns: 1fr; } }
        </style>`).appendTo("head");
    }
})();
