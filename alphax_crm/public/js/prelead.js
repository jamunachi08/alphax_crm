frappe.ui.form.on("AlphaX PreLead", {
    setup(frm) {
        frm.set_query("status", () => ({ filters: { is_active: 1 } }));
    },
    refresh(frm) {
        if (frm.doc.converted) {
            // Already converted — the real record now lives on the Lead.
            // Lock the whole form so it can't drift out of sync or confuse
            // anyone into thinking further edits here matter. Server-side
            // validate() enforces this too, for API/script access.
            frm.disable_form();
            frm.dashboard.set_headline_alert(
                __("Converted to Lead {0} — this PreLead is now read-only.", [frm.doc.lead || ""]),
                "blue"
            );
        }
        frm.add_custom_button(__("Ask AI"), () => alphax_ready(["alphax_open_ai_assistant", "alphax_ai_form_context"])
            && window.alphax_open_ai_assistant(window.alphax_ai_form_context(frm)), __("AlphaX"));
        if (!frm.is_new()) {
            // Converted: follow-ups continue on the Lead; the panel here stays readable as history.
            if (alphax_ready(["alphax_followup_menu", "alphax_render_followups", "alphax_log_followup"])) {
                alphax_guard("follow-ups", () => (frm.doc.converted ? window.alphax_render_followups(frm) : window.alphax_followup_menu(frm)));
            }
        }
        if (frm.doc.lead) {
            frm.add_custom_button(__("Open Lead"), () => frappe.set_route("Form", "Lead", frm.doc.lead));
        }
        if (frm.doc.converted) {
            // Nothing below matters once locked — status can't change anyway.
        } else if (frm.doc.conversion_failed) {
            // Persistent — not a one-time toast. Stays until conversion
            // actually succeeds (see _clear_conversion_failure server-side),
            // so re-opening the record later still shows why it's stuck.
            frm.dashboard.set_headline_alert(
                __("Conversion to Lead failed and hasn't succeeded since: {0}",
                   [frappe.utils.escape_html(frm.doc.conversion_error || "")]),
                "red"
            );
        } else if (frm.doc.status) {
            frappe.db.get_value("AlphaX PreLead Status", frm.doc.status, "behavior").then((r) => {
                const b = r.message && r.message.behavior;
                if (b && b !== "None") {
                    frm.dashboard.set_headline_alert(
                        __("Setting this status will: {0}", [b]),
                        b === "Convert to Lead" ? "green" : "blue"
                    );
                }
            });
        }
    },
});

// ---------------------------------------------------------------------------
// Safety net (0.50.1). Parts of this form come from AlphaX's shared desk scripts. If the browser still runs an
// older cached copy, a missing helper must not break the form: an error here would also stop ERPNext's own
// form script (Create / Action menus). Missing helpers -> one "please reload" note; any error -> console only.
// ---------------------------------------------------------------------------
function alphax_ready(names) {
    const missing = (names || []).filter((n) => typeof window[n] !== "function");
    if (missing.length && !window.__ax_reload_noted) {
        window.__ax_reload_noted = true;
        console.warn("AlphaX CRM: shared desk scripts are out of date; missing", missing);
        frappe.msgprint({
            title: __("Please reload"), indicator: "orange",
            message: __("AlphaX CRM was updated and this browser is still using the previous version. Press <b>Ctrl + Shift + R</b> (Mac: <b>Cmd + Shift + R</b>) to load the new version."),
        });
    }
    return !missing.length;
}

function alphax_guard(label, fn) {
    try {
        return fn();
    } catch (e) {
        console.error(`AlphaX CRM: ${label} failed`, e);
    }
}
