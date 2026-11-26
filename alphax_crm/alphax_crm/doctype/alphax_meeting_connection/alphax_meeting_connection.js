// AlphaX Meeting Connection — connect Teams / Zoom / Google Meet / Webex so scheduled follow-ups create real meetings.
const AX_SETUP = {
    "Microsoft Teams": `<ol>
        <li>${__("In the Microsoft Entra admin center, open <b>App registrations → New registration</b> (single tenant).")}</li>
        <li>${__("Copy the <b>Directory (tenant) ID</b> and <b>Application (client) ID</b> into this form.")}</li>
        <li>${__("<b>Certificates & secrets → New client secret</b>; paste the secret <i>value</i> as Client Secret.")}</li>
        <li>${__("<b>API permissions → Microsoft Graph → Application permissions</b>: add <code>Calendars.ReadWrite</code> and <code>User.Read.All</code>, then <b>Grant admin consent</b>.")}</li>
        <li>${__("Default Host Account: a licensed Microsoft 365 / Teams user (for example a shared sales mailbox user).")}</li>
        <li>${__("Optional: limit the app to sales mailboxes with an Exchange application access policy.")}</li></ol>`,
    "Zoom": `<ol>
        <li>${__("In the Zoom App Marketplace, <b>Develop → Build App → Server-to-Server OAuth</b>.")}</li>
        <li>${__("Copy <b>Account ID</b>, <b>Client ID</b> and <b>Client Secret</b> into this form.")}</li>
        <li>${__("Scopes: <code>meeting:write:admin</code>, <code>meeting:read:admin</code>, <code>user:read:admin</code> (newer apps: the matching <code>meeting:write:meeting:admin</code> / <code>user:read:user:admin</code>). Activate the app.")}</li>
        <li>${__("Default Host Account: a licensed Zoom user's email. Organizers with their own Zoom user (same email) host their own meetings.")}</li></ol>
        <p class="text-muted">${__("Zoom does not email invitations itself: AlphaX sends its calendar invitation with the Zoom link when “Email the invitation” is ticked.")}</p>`,
    "Google Meet": `<ol>
        <li>${__("In Google Cloud, create a project, enable the <b>Google Calendar API</b>, and create a <b>service account</b> with a JSON key.")}</li>
        <li>${__("In the Google Workspace Admin console, <b>Security → API controls → Domain-wide delegation</b>: add the service account's client ID with scope <code>https://www.googleapis.com/auth/calendar</code>.")}</li>
        <li>${__("Attach the JSON key here as a <b>private</b> file.")}</li>
        <li>${__("Default Host Account: a Google Workspace user whose calendar holds meetings when the organizer has no Workspace account.")}</li></ol>`,
    "Webex": `<ol>
        <li>${__("In the Webex Developer portal, create an <b>Integration</b> (or Service App) with the <code>meeting:schedules_write</code> and <code>meeting:schedules_read</code> scopes (add <code>meeting:admin_schedule_write</code> to schedule on behalf of organizers).")}</li>
        <li>${__("Authorise it once and paste the <b>Access Token</b> and <b>Refresh Token</b>, plus the integration's <b>Client ID</b> and <b>Client Secret</b> so AlphaX renews the token by itself.")}</li>
        <li>${__("Default Host Account: the Webex user the token belongs to.")}</li></ol>`,
};

frappe.ui.form.on("AlphaX Meeting Connection", {
    refresh(frm) {
        frm.trigger("platform");
        if (!frm.is_new()) {
            frm.add_custom_button(__("Test Connection"), () => frappe.call({
                method: "alphax_crm.crm.meeting_connect.test_connection", args: { platform: frm.doc.name }, freeze: true,
                freeze_message: __("Connecting to {0}…", [__(frm.doc.platform)]),
            }).then((r) => {
                const m = r.message || {};
                frappe.msgprint({ title: m.ok ? __("Connected") : __("Not connected"), indicator: m.ok ? "green" : "red",
                    message: frappe.utils.escape_html(m.message || "") });
                frm.reload_doc();
            })).addClass("btn-primary");
        }
        if (frm.doc.last_test_result) {
            const ok = frm.doc.last_test_result.startsWith("OK");
            frm.dashboard.set_headline(`<span class="indicator ${ok ? "green" : "red"}">${frappe.utils.escape_html(frm.doc.last_test_result)}</span>`);
        }
    },
    platform(frm) {
        const help = AX_SETUP[frm.doc.platform];
        frm.get_field("setup_help").$wrapper.html(help ? `<div class="small" style="margin-bottom:10px"><b>${__("How to connect {0}", [__(frm.doc.platform)])}</b>${help}</div>` : "");
    },
});
