// AlphaX CRM — Schedule Follow-up (crm/schedule.py).
// A meeting screen laid out like a Teams / Outlook new-meeting form: title, attendees, start and end with
// All day / Time zones / Make recurring, platform + join link, reminders (pop-up / email), attachments, agenda.
// Open with frappe.route_options = { reference_doctype, reference_name, [source_follow_up], [start_date] }
// or /app/alphax-schedule/<FUS-…> to edit.

const AX_PLATFORMS = [
    ["Microsoft Teams", "#5b5fc7", "video"], ["Zoom", "#2d8cff", "video"], ["Google Meet", "#00897b", "video"],
    ["Webex", "#07c160", "video"], ["Phone Call", "#6b7280", "call"], ["WhatsApp", "#25d366", "message"],
    ["On-site Visit", "#b45309", "map-pin"], ["Other", "#6b7280", "dot-horizontal"],
];
const AX_REPEAT = ["Does not repeat", "Daily", "Every working day", "Weekly", "Monthly"];

frappe.pages["alphax-schedule"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Schedule Follow-up"), single_column: true });
    wrapper.ax = new AlphaXScheduler(page, wrapper);
};

frappe.pages["alphax-schedule"].on_page_show = function (wrapper) {
    const opts = Object.assign({}, frappe.route_options || {});
    frappe.route_options = null;
    const route = frappe.get_route();
    if (route[1]) opts.name = decodeURIComponent(route[1]);
    wrapper.ax.open(opts);
};

class AlphaXScheduler {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$body = $(`<div class="ax-sched"></div>`).appendTo(page.main);
        this.inject_css();
    }

    // ------------------------------------------------------------------ load
    open(opts) {
        this.opts = opts || {};
        if (!this.opts.name && !(this.opts.reference_doctype && this.opts.reference_name)) {
            if (this.state && (this.state.name || this.state.reference)) return; // returning to the page
            this.$body.html(`<div class="ax-empty">${__("Open Schedule Follow-up from a Lead, Opportunity or PreLead (button “Schedule Follow-up”).")}
                <br><br><a href="/app/alphax-follow-up-schedule/view/calendar/default">${__("Open the follow-up calendar")}</a></div>`);
            return;
        }
        frappe.call({
            method: "alphax_crm.crm.schedule.get_schedule_context",
            args: { reference_doctype: this.opts.reference_doctype, reference_name: this.opts.reference_name, name: this.opts.name },
            freeze: true,
        }).then((r) => this.render(r.message || {}));
    }

    render(ctx) {
        this.ctx = ctx;
        const doc = ctx.doc;
        const d = ctx.defaults || {};
        const now = moment();
        const start = doc ? moment(doc.start_local) : this.default_start(now);
        const end = doc ? moment(doc.end_local) : start.clone().add(d.duration || 30, "minutes");
        this.state = {
            name: doc ? doc.name : null,
            status: doc ? doc.status : "Scheduled",
            reference: ctx.reference,
            source_follow_up: doc ? doc.source_follow_up : this.opts.source_follow_up || null,
            tz: doc ? doc.display_tz : ctx.system_tz,
            can_write: doc ? doc.can_write : true,
            repeat_open: !!(doc && doc.repeat && doc.repeat !== "Does not repeat"),
        };
        this.$body.empty();
        this.$body.html(this.layout());
        this.set_title_bar();

        // title
        this.$("title").val(doc ? doc.subject : "").attr("placeholder", __("Add a title"));
        // attendees
        this.internal = this.control("internal", { fieldtype: "MultiSelectPills", placeholder: __("Add required attendees"),
            get_data: (txt) => frappe.db.get_link_options("User", txt, { user_type: "System User", enabled: 1 }) });
        const internal = doc ? (doc.attendees || []).filter((a) => a.attendee_type === "Internal").map((a) => a.user) : [];
        this.internal.set_value(internal);
        this.external = doc ? (doc.attendees || []).filter((a) => a.attendee_type === "External").map((a) => a.email) : [];
        this.render_external();
        // when
        this.start_date = this.control("start_date", { fieldtype: "Date" });
        this.end_date = this.control("end_date", { fieldtype: "Date" });
        this.start_date.set_value(start.format("YYYY-MM-DD"));
        this.end_date.set_value(end.format("YYYY-MM-DD"));
        this.fill_times(this.$("start_time"), start.format("HH:mm:ss"));
        this.fill_times(this.$("end_time"), end.format("HH:mm:ss"));
        this.$("all_day").prop("checked", !!(doc && doc.all_day));
        this.$("tz_on").prop("checked", this.state.tz !== ctx.system_tz);
        this.fill_tz();
        // repeat
        this.$("repeat").html(AX_REPEAT.map((r) => `<option value="${r}">${__(r)}</option>`).join(""));
        this.$("repeat").val(doc && doc.repeat ? doc.repeat : "Weekly");
        this.$("repeat_every").val(doc ? doc.repeat_every || 1 : 1);
        this.repeat_until = this.control("repeat_until", { fieldtype: "Date" });
        if (doc && doc.repeat_until) this.repeat_until.set_value(doc.repeat_until);
        // where
        this.platform = doc ? doc.platform : d.platform;
        this.render_platforms();
        this.$("meeting_link").val(doc ? doc.meeting_link || "" : "");
        this.$("location").val(doc ? doc.location || "" : "");
        // reminders
        this.reminders = doc ? (doc.reminders || []).filter((r) => r.popup || r.email)
            .map((r) => ({ remind_before: r.remind_before, popup: r.popup, email: r.email }))
            : (d.reminders || []).map((r) => Object.assign({}, r));
        this.render_reminders();
        // invitation
        this.$("send_invitation").prop("checked", doc ? !!doc.send_invitation : !!d.send_invitation);
        // agenda
        this.agenda = this.control("agenda", { fieldtype: "Text Editor", placeholder: __("Type details for this meeting") });
        this.agenda.set_value(doc ? doc.agenda || "" : "");
        // attachments
        this.render_attachments(ctx.attachments || []);
        this.bind();
        this.sync_ui();
        if (!this.state.can_write) this.$body.find("input,select,textarea,button.ax-edit").prop("disabled", true);
    }

    default_start(now) {
        if (this.opts.start_date) return moment(this.opts.start_date + " 10:00:00");
        const m = now.clone().add(30, "minutes");
        return m.minutes(m.minutes() < 30 ? 30 : 60).seconds(0); // next half hour, like Teams
    }

    // ------------------------------------------------------------------ layout
    layout() {
        const ref = this.ctx.reference || {};
        const row = (icon, label, body, cls = "") => `<div class="ax-row ${cls}">
            <div class="ax-label">${frappe.utils.icon(icon, "sm")}<span>${label}</span></div><div class="ax-field">${body}</div></div>`;
        return `
        <div class="ax-card">
          ${row("edit", __("Title"), `<input data-ax="title" class="ax-title ax-edit" maxlength="140">`)}
          ${row("users", __("Attendees"), `<div data-ax-control="internal"></div>`)}
          ${row("mail", __("External"), `<div class="ax-chips" data-ax="external_chips"></div>
              <input data-ax="external_input" class="ax-input ax-edit" placeholder="${__("Add client emails (Enter or comma)")}">
              <div data-ax="external_suggest"></div>`)}
          ${row("calendar", __("Start time"), `<div class="ax-when">
              <div class="ax-date" data-ax-control="start_date"></div>
              <select data-ax="start_time" class="ax-select ax-time ax-edit"></select>
              <label class="ax-check"><input type="checkbox" data-ax="all_day" class="ax-edit"> ${__("All day")}</label>
              <label class="ax-check"><input type="checkbox" data-ax="tz_on" class="ax-edit"> ${frappe.utils.icon("globe", "sm")} ${__("Time zones")}</label>
            </div>`)}
          ${row("calendar", __("End time"), `<div class="ax-when">
              <div class="ax-date" data-ax-control="end_date"></div>
              <select data-ax="end_time" class="ax-select ax-time ax-edit"></select>
              <span class="ax-duration" data-ax="duration"></span>
              <a class="ax-link ax-edit" data-ax="make_recurring">${frappe.utils.icon("refresh", "sm")} ${__("Make recurring")}</a>
            </div>`)}
          ${row("globe", __("Time zone"), `<select data-ax="tz" class="ax-select ax-wide ax-edit"></select>
              <div class="ax-hint" data-ax="tz_hint"></div>`, "ax-tz-row")}
          ${row("refresh", __("Repeat"), `<div class="ax-when">
              <select data-ax="repeat" class="ax-select ax-edit"></select>
              <span class="ax-every">${__("every")} <input type="number" min="1" max="30" data-ax="repeat_every" class="ax-input ax-num ax-edit">
                <span data-ax="repeat_unit"></span></span>
              <span>${__("until")}</span><div class="ax-date" data-ax-control="repeat_until"></div>
              <a class="ax-link ax-edit" data-ax="remove_repeat">${__("Remove")}</a>
            </div><div class="ax-hint" data-ax="repeat_hint"></div>`, "ax-repeat-row")}
          ${row("video", __("Platform"), `<div class="ax-platforms" data-ax="platforms"></div>`)}
          ${row("link", __("Meeting link"), `<div class="ax-when"><input data-ax="meeting_link" class="ax-input ax-wide ax-edit"
              placeholder="${__("Paste the Teams / Zoom / Meet link")}">
              <button class="btn btn-default btn-xs" data-ax="join_test">${__("Open")}</button></div>`, "ax-link-row")}
          ${row("map-pin", __("Location"), `<input data-ax="location" class="ax-input ax-wide ax-edit" placeholder="${__("Add a location")}">`)}
          ${row("file", __("Regarding"), `<div class="ax-ref">
              <a href="/app/${frappe.router.slug(ref.doctype || "")}/${encodeURIComponent(ref.name || "")}">${__(ref.doctype || "")} ${frappe.utils.escape_html(ref.name || "")}</a>
              · <b>${frappe.utils.escape_html(ref.title || "")}</b>
              ${ref.lead_owner ? ` · ${__("Lead Owner")}: ${frappe.utils.escape_html(ref.lead_owner_name || ref.lead_owner)}` : ""}
              <span class="ax-status" data-ax="status"></span></div>`)}
          ${row("notification", __("Reminders"), `<div data-ax="reminders"></div>
              <a class="ax-link ax-edit" data-ax="add_reminder">+ ${__("Add reminder")}</a>
              <div class="ax-hint">${__("Reminders go to you, the Lead Owner and internal attendees.")}</div>`)}
          ${row("attachment", __("Attachments"), `<div data-ax="attachments"></div>
              <button class="btn btn-default btn-xs ax-edit" data-ax="attach">${frappe.utils.icon("upload", "xs")} ${__("Attach file")}</button>`)}
          ${row("mail", __("Invitation"), `<label class="ax-check"><input type="checkbox" data-ax="send_invitation" class="ax-edit">
              ${__("Email the invitation (.ics) with the attachments to the attendees")}</label>
              <div class="ax-hint" data-ax="invite_hint"></div>`)}
          ${row("list", __("Details"), `<div data-ax-control="agenda" class="ax-agenda"></div>`)}
        </div>`;
    }

    set_title_bar() {
        const p = this.page;
        p.clear_actions_menu && p.clear_actions_menu();
        p.clear_inner_toolbar && p.clear_inner_toolbar();
        p.clear_primary_action();
        p.clear_secondary_action();
        p.set_title(this.state.name ? this.state.name : __("Schedule Follow-up"));
        if (!this.state.can_write) return;
        p.set_primary_action(__("Save"), () => this.save());
        const ref = this.state.reference || {};
        p.add_inner_button(__("Back to {0}", [__(ref.doctype || "")]), () => frappe.set_route("Form", ref.doctype, ref.name));
        if (this.state.name) {
            p.add_inner_button(__("Log Outcome"), () => this.log_outcome());
            if (this.state.status === "Scheduled") p.add_inner_button(__("Cancel Meeting"), () => this.cancel_meeting());
            p.add_inner_button(__("Open Form"), () => frappe.set_route("Form", "AlphaX Follow-up Schedule", this.state.name));
        }
        p.add_inner_button(__("Calendar"), () => frappe.set_route("List", "AlphaX Follow-up Schedule", "Calendar", "default"));
    }

    // ------------------------------------------------------------------ helpers
    $(key) { return this.$body.find(`[data-ax="${key}"]`); }

    control(key, df) {
        const parent = this.$body.find(`[data-ax-control="${key}"]`);
        const c = frappe.ui.form.make_control({ parent, df: Object.assign({ fieldname: key, label: "" }, df), render_input: true,
            only_input: df.fieldtype === "Date" });
        c.refresh();
        return c;
    }

    fill_times($sel, value) {
        const opts = [];
        for (let m = 0; m < 24 * 60; m += 15) {
            const t = moment().startOf("day").add(m, "minutes");
            opts.push([t.format("HH:mm:00"), t.format("h:mm A")]);
        }
        if (value && !opts.find((o) => o[0] === value)) opts.push([value, moment(value, "HH:mm:ss").format("h:mm A")]);
        opts.sort((a, b) => a[0].localeCompare(b[0]));
        $sel.html(opts.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")).val(value);
    }

    fill_tz() {
        let zones = [];
        try { zones = Intl.supportedValuesOf("timeZone"); } catch (e) { zones = [this.ctx.system_tz, "UTC"]; }
        if (!zones.includes(this.ctx.system_tz)) zones.unshift(this.ctx.system_tz);
        this.$("tz").html(zones.map((z) => `<option value="${z}">${z.replace(/_/g, " ")}${z === this.ctx.system_tz ? " (" + __("system") + ")" : ""}</option>`).join(""))
            .val(this.state.tz);
    }

    start_m() { return moment(`${this.start_date.get_value()} ${this.$("start_time").val() || "00:00:00"}`); }
    end_m() { return moment(`${this.end_date.get_value()} ${this.$("end_time").val() || "00:00:00"}`); }

    render_platforms() {
        this.$("platforms").html(AX_PLATFORMS.map(([name, color, icon]) =>
            `<button class="ax-chip ax-edit ${name === this.platform ? "active" : ""}" data-platform="${name}" style="--c:${color}">
                ${frappe.utils.icon(icon, "xs")} ${__(name)}</button>`).join(""));
    }

    render_external() {
        const ref = this.ctx.reference || {};
        this.$("external_chips").html(this.external.map((e, i) =>
            `<span class="ax-pill">${frappe.utils.escape_html(e)} <a data-remove-ext="${i}" class="ax-edit">×</a></span>`).join(""));
        const suggest = ref.email && !this.external.includes(ref.email)
            ? `<a class="ax-link ax-edit" data-add-ext="${frappe.utils.escape_html(ref.email)}">+ ${__("Add {0}", [frappe.utils.escape_html(ref.email)])}</a>` : "";
        this.$("external_suggest").html(suggest);
    }

    add_external(value) {
        (value || "").split(/[,;\s]+/).map((v) => v.trim()).filter(Boolean).forEach((e) => {
            if (!frappe.utils.validate_type(e, "email")) {
                frappe.show_alert({ message: __("{0} is not a valid email", [frappe.utils.escape_html(e)]), indicator: "orange" });
                return;
            }
            if (!this.external.includes(e)) this.external.push(e);
        });
        this.render_external();
    }

    render_reminders() {
        const opts = this.ctx.reminder_options || [];
        const html = this.reminders.map((r, i) => `<div class="ax-reminder" data-i="${i}">
            <select class="ax-select ax-edit" data-r="remind_before">${opts.map((o) => `<option value="${o}" ${o === r.remind_before ? "selected" : ""}>${__(o)}</option>`).join("")}</select>
            <label class="ax-check"><input type="checkbox" class="ax-edit" data-r="popup" ${r.popup ? "checked" : ""}> ${__("Pop-up")}</label>
            <label class="ax-check"><input type="checkbox" class="ax-edit" data-r="email" ${r.email ? "checked" : ""}> ${__("Email")}</label>
            <a class="ax-link ax-edit" data-r="remove">${frappe.utils.icon("delete", "xs")}</a></div>`).join("");
        this.$("reminders").html(html || `<div class="ax-hint">${__("No reminders")}</div>`);
    }

    render_attachments(files) {
        this.files = files || [];
        this.$("attachments").html(this.files.map((f) =>
            `<div class="ax-file">${frappe.utils.icon("file", "xs")} <a href="${encodeURI(f.file_url)}" target="_blank">${frappe.utils.escape_html(f.file_name || f.file_url)}</a></div>`).join("")
            || `<div class="ax-hint">${__("No attachments")}</div>`);
    }

    sync_ui() {
        const all_day = this.$("all_day").is(":checked");
        this.$("start_time").add(this.$("end_time")).toggle(!all_day);
        this.$body.find(".ax-tz-row").toggle(this.$("tz_on").is(":checked"));
        this.$body.find(".ax-repeat-row").toggle(this.state.repeat_open);
        this.$("make_recurring").toggle(!this.state.repeat_open);
        const repeat = this.$("repeat").val();
        this.$body.find(".ax-every").toggle(repeat !== "Every working day");
        this.$("repeat_unit").text({ Daily: __("day(s)"), Weekly: __("week(s)"), Monthly: __("month(s)") }[repeat] || "");
        this.$("repeat_hint").text(repeat === "Every working day" ? __("Uses the working days set in AlphaX CRM Settings.") : "");
        const online = ["Microsoft Teams", "Zoom", "Google Meet", "Webex"].includes(this.platform);
        this.$body.find(".ax-link-row").toggle(online || !!this.$("meeting_link").val());
        const mins = this.end_m().diff(this.start_m(), "minutes");
        this.$("duration").text(all_day ? "" : mins > 0 ? (mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60 ? (mins % 60) + "m" : ""}` : `${mins}m`) : __("ends before it starts"))
            .toggleClass("ax-bad", !all_day && mins <= 0);
        const tz = this.$("tz").val();
        this.$("tz_hint").text(tz && tz !== this.ctx.system_tz
            ? __("Times above are in {0}; they are saved and reminded in {1} time.", [tz, this.ctx.system_tz]) : "");
        const st = this.state.status;
        this.$("status").html(this.state.name ? `<span class="indicator-pill ${st === "Scheduled" ? "blue" : st === "Completed" ? "green" : "gray"}">${__(st)}</span>` : "");
        const sent = this.ctx.doc && this.ctx.doc.invitation_sent_on;
        this.$("invite_hint").text(sent ? __("Last sent {0}. It is sent again when the time or link changes.", [frappe.datetime.comment_when(sent)])
            : __("Internal attendees also get the ERP link; clients get a clean invitation."));
        this.page.set_primary_action(this.$("send_invitation").is(":checked") ? __("Save & Send") : __("Save"), () => this.save());
    }

    // ------------------------------------------------------------------ events
    bind() {
        const me = this;
        let last_start = this.start_m();
        const keep_duration = () => {
            const dur = this.end_m().diff(last_start, "minutes");
            const s = this.start_m();
            if (dur > 0) {
                const e = s.clone().add(dur, "minutes");
                this.end_date.set_value(e.format("YYYY-MM-DD"));
                this.fill_times(this.$("end_time"), e.format("HH:mm:00"));
            }
            last_start = s;
            this.sync_ui();
        };
        this.start_date.$input.on("change", () => setTimeout(keep_duration, 50));
        this.$("start_time").on("change", keep_duration);
        this.end_date.$input.on("change", () => setTimeout(() => this.sync_ui(), 50));
        this.$body.on("change", '[data-ax="end_time"],[data-ax="all_day"],[data-ax="tz_on"],[data-ax="tz"],[data-ax="repeat"],[data-ax="send_invitation"]', () => this.sync_ui());
        this.$body.on("input", '[data-ax="meeting_link"]', () => this.sync_ui());
        this.$("make_recurring").on("click", () => { this.state.repeat_open = true; this.sync_ui(); });
        this.$("remove_repeat").on("click", () => { this.state.repeat_open = false; this.sync_ui(); });
        this.$("platforms").on("click", "[data-platform]", function () {
            me.platform = $(this).attr("data-platform");
            me.render_platforms();
            me.sync_ui();
        });
        this.$("join_test").on("click", () => {
            const url = (this.$("meeting_link").val() || "").trim();
            if (url) window.open(/^https?:\/\//i.test(url) ? url : "https://" + url, "_blank", "noopener");
        });
        this.$("external_input").on("keydown", function (e) {
            if (e.key === "Enter" || e.key === ",") { e.preventDefault(); me.add_external(this.value); this.value = ""; }
        }).on("blur", function () { if (this.value) { me.add_external(this.value); this.value = ""; } });
        this.$body.on("click", "[data-remove-ext]", function () { me.external.splice(+$(this).attr("data-remove-ext"), 1); me.render_external(); });
        this.$body.on("click", "[data-add-ext]", function () { me.add_external($(this).attr("data-add-ext")); });
        this.$("add_reminder").on("click", () => {
            this.reminders.push({ remind_before: "15 minutes before", popup: 1, email: 1 });
            this.render_reminders();
        });
        this.$("reminders").on("change", "[data-r]", function () {
            const i = +$(this).closest(".ax-reminder").attr("data-i");
            const key = $(this).attr("data-r");
            me.reminders[i][key] = this.type === "checkbox" ? (this.checked ? 1 : 0) : this.value;
        }).on("click", '[data-r="remove"]', function () {
            me.reminders.splice(+$(this).closest(".ax-reminder").attr("data-i"), 1);
            me.render_reminders();
        });
        this.$("attach").on("click", () => this.attach());
    }

    // ------------------------------------------------------------------ actions
    collect() {
        const all_day = this.$("all_day").is(":checked");
        const s = this.start_m(), e = this.end_m();
        if (!this.start_date.get_value()) frappe.throw(__("Pick a start date."));
        if (!all_day && e.diff(s, "minutes") <= 0) frappe.throw(__("The meeting ends before it starts."));
        return {
            name: this.state.name, reference_doctype: this.state.reference.doctype, reference_name: this.state.reference.name,
            source_follow_up: this.state.source_follow_up,
            subject: this.$("title").val(), platform: this.platform, all_day: all_day ? 1 : 0,
            time_zone: this.$("tz_on").is(":checked") ? this.$("tz").val() : this.ctx.system_tz,
            start: s.format("YYYY-MM-DD HH:mm:ss"), end: (all_day ? moment(`${this.end_date.get_value()} 23:59:59`) : e).format("YYYY-MM-DD HH:mm:ss"),
            repeat: this.state.repeat_open ? this.$("repeat").val() : "Does not repeat",
            repeat_every: this.$("repeat_every").val() || 1, repeat_until: this.state.repeat_open ? this.repeat_until.get_value() || null : null,
            meeting_link: this.$("meeting_link").val(), location: this.$("location").val(),
            internal: this.internal.get_value() || [], external: this.external,
            reminders: this.reminders, agenda: this.agenda.get_value() || "",
            send_invitation: this.$("send_invitation").is(":checked") ? 1 : 0,
        };
    }

    save(after) {
        const data = this.collect();
        return frappe.call({ method: "alphax_crm.crm.schedule.save_schedule", args: { data }, freeze: true,
            freeze_message: data.send_invitation ? __("Saving and sending the invitation…") : __("Saving…") })
            .then((r) => {
                const name = r.message && r.message.name;
                frappe.show_alert({ message: __("Follow-up scheduled · reminders set"), indicator: "green" });
                if (after) return after(name);
                const route = frappe.get_route();
                if (route[0] === "alphax-schedule" && decodeURIComponent(route[1] || "") === name) this.open({ name });
                else frappe.set_route("alphax-schedule", name);
            });
    }

    attach() {
        const go = (name) => new frappe.ui.FileUploader({
            doctype: "AlphaX Follow-up Schedule", docname: name, folder: "Home/Attachments",
            on_success: () => frappe.call({ method: "alphax_crm.crm.schedule.get_schedule_context", args: { name } })
                .then((r) => { this.ctx.attachments = r.message.attachments; this.render_attachments(r.message.attachments); }),
        });
        if (this.state.name) return go(this.state.name);
        frappe.confirm(__("The meeting is saved first so files can be attached to it. Continue?"), () =>
            this.save((name) => { this.state.name = name; history.replaceState(null, "", `/app/alphax-schedule/${encodeURIComponent(name)}`); this.set_title_bar(); go(name); }));
    }

    log_outcome() {
        const ref = this.state.reference;
        const online = ["Microsoft Teams", "Zoom", "Google Meet", "Webex"].includes(this.platform);
        window.alphax_log_followup({ doctype: ref.doctype, docname: ref.name, reload_doc() {} }, {
            schedule: this.state.name, channel: "Meeting", meeting_type: online ? "Online Meeting" : "On-site Meeting",
            title: __("Log Outcome · {0}", [this.$("title").val() || this.state.name]),
            after: () => this.open({ name: this.state.name }),
        });
    }

    cancel_meeting() {
        const sent = this.ctx.doc && this.ctx.doc.invitation_sent_on;
        frappe.confirm(sent ? __("Cancel this meeting? Attendees who got the invitation are sent a cancellation.") : __("Cancel this meeting?"), () =>
            frappe.call({ method: "alphax_crm.crm.schedule.cancel_schedule", args: { name: this.state.name }, freeze: true })
                .then(() => { frappe.show_alert({ message: __("Meeting cancelled"), indicator: "orange" }); this.open({ name: this.state.name }); }));
    }

    inject_css() {
        if (document.getElementById("ax-sched-css")) return;
        $(`<style id="ax-sched-css">
        .ax-sched { max-width: 980px; margin: 0 auto 40px; }
        .ax-sched .ax-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 8px 0; }
        .ax-sched .ax-row { display: grid; grid-template-columns: 150px 1fr; gap: 12px; align-items: center; padding: 10px 20px; border-bottom: 1px solid var(--border-color); }
        .ax-sched .ax-row:last-child { border-bottom: none; }
        .ax-sched .ax-label { color: var(--text-muted); display: flex; gap: 8px; align-items: center; font-size: 13px; }
        .ax-sched .ax-title { width: 100%; border: none; border-bottom: 2px solid var(--border-color); font-size: 20px; padding: 4px 0; background: transparent; outline: none; }
        .ax-sched .ax-title:focus { border-bottom-color: #5b5fc7; }
        .ax-sched .ax-when { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
        .ax-sched .ax-date { width: 160px; }
        .ax-sched .ax-select, .ax-sched .ax-input { height: 32px; border: 1px solid var(--border-color); border-radius: 4px; padding: 0 8px; background: var(--control-bg); }
        .ax-sched .ax-time { width: 120px; }
        .ax-sched .ax-wide { width: 100%; max-width: 560px; }
        .ax-sched .ax-num { width: 60px; }
        .ax-sched .ax-check { display: inline-flex; gap: 6px; align-items: center; margin: 0; font-weight: normal; cursor: pointer; }
        .ax-sched .ax-link { color: #5b5fc7; cursor: pointer; display: inline-flex; gap: 4px; align-items: center; }
        .ax-sched .ax-hint { color: var(--text-muted); font-size: 12px; margin-top: 4px; }
        .ax-sched .ax-duration { color: var(--text-muted); font-size: 12px; }
        .ax-sched .ax-bad { color: var(--red-500); }
        .ax-sched .ax-platforms { display: flex; flex-wrap: wrap; gap: 6px; }
        .ax-sched .ax-chip { border: 1px solid var(--border-color); background: var(--card-bg); border-radius: 16px; padding: 4px 12px; font-size: 12px; display: inline-flex; gap: 6px; align-items: center; }
        .ax-sched .ax-chip.active { border-color: var(--c); background: var(--c); color: #fff; }
        .ax-sched .ax-chip.active .icon { stroke: #fff; }
        .ax-sched .ax-pill { display: inline-flex; gap: 6px; background: var(--subtle-fg); border-radius: 12px; padding: 2px 10px; margin: 0 6px 6px 0; font-size: 12px; }
        .ax-sched .ax-pill a { cursor: pointer; }
        .ax-sched .ax-reminder { display: flex; gap: 12px; align-items: center; margin-bottom: 6px; }
        .ax-sched .ax-file { margin-bottom: 4px; }
        .ax-sched .ax-agenda .ql-editor { min-height: 160px; }
        .ax-sched .ax-empty { text-align: center; color: var(--text-muted); padding: 80px 20px; }
        .ax-sched .ax-ref .ax-status { margin-left: 8px; }
        @media (max-width: 720px) { .ax-sched .ax-row { grid-template-columns: 1fr; } }
        </style>`).appendTo("head");
    }
}
