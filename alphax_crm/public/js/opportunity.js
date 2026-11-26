frappe.ui.form.on("Opportunity", {
    refresh(frm) {
        if (frm.is_new()) return;
        frm.add_custom_button(__("Ask AI"), () => alphax_ready(["alphax_open_ai_assistant", "alphax_ai_form_context"])
            && window.alphax_open_ai_assistant(window.alphax_ai_form_context(frm)), __("AlphaX"));
        if (alphax_ready(["alphax_followup_menu", "alphax_log_followup", "alphax_open_scheduler"])) {
            alphax_guard("follow-ups", () => window.alphax_followup_menu(frm));
        }
        frm.add_custom_button(
            __("Refresh AI Brief"),
            () => {
                frappe.call({
                    method: "alphax_crm.crm.opportunity.refresh_brief",
                    args: { opportunity: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Asking AlphaX AI..."),
                    callback: (r) => {
                        if (r.message) {
                            frappe.msgprint({ title: __("Opportunity brief"), message: frappe.utils.escape_html(r.message) });
                        }
                    },
                });
            },
            __("AlphaX")
        );
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
