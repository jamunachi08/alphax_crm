frappe.ui.form.on("Opportunity", {
    refresh(frm) {
        if (frm.is_new()) return;
        frm.add_custom_button(__("Ask AI"), () => window.alphax_open_ai_assistant(window.alphax_ai_form_context(frm)), __("AlphaX"));
        window.alphax_followup_menu(frm);
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
