// AlphaX CRM — operator actions on the Prospect form.
frappe.ui.form.on("AlphaX Prospect", {
    refresh(frm) {
        if (frm.is_new()) return;

        if (frm.doc.status !== "Converted" && frappe.model.can_create("Lead")) {
            frm.add_custom_button(__("Convert to Lead"), () => {
                frappe.confirm(__("Create a Lead from this prospect?"), () => {
                    frappe.call({
                        method: "alphax_crm.api.prospect.convert_to_lead",
                        args: { names: [frm.doc.name] },
                        freeze: true,
                        callback: (r) => {
                            const res = r.message || {};
                            if (res.converted && res.converted.length) {
                                frappe.show_alert({
                                    message: __("Lead {0} created", [res.converted[0].lead]),
                                    indicator: "green",
                                });
                                frm.reload_doc();
                            } else if (res.failed && res.failed.length) {
                                frappe.msgprint({
                                    title: __("Conversion Failed"),
                                    message: frappe.utils.escape_html(res.failed[0].reason),
                                    indicator: "red",
                                });
                            }
                        },
                    });
                });
            }).addClass("btn-primary");
        }

        frm.add_custom_button(__("Log Call"), () => {
            const d = new frappe.ui.Dialog({
                title: __("Log Call"),
                fields: [
                    {
                        fieldname: "outcome",
                        label: __("Outcome"),
                        fieldtype: "Select",
                        options: "Contacted\nInterested\nNot Interested\nInvalid",
                        reqd: 1,
                    },
                    { fieldname: "notes", label: __("Notes"), fieldtype: "Small Text" },
                ],
                primary_action_label: __("Save"),
                primary_action(values) {
                    d.hide();
                    frappe.call({
                        method: "alphax_crm.api.prospect.log_call",
                        args: { name: frm.doc.name, outcome: values.outcome, notes: values.notes || "" },
                        callback: () => frm.reload_doc(),
                    });
                },
            });
            d.show();
        });

        if (frm.doc.lead) {
            frm.add_custom_button(__("Open Lead"), () => frappe.set_route("Form", "Lead", frm.doc.lead));
        }
    },
});
