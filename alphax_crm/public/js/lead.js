// AlphaX CRM — live data-quality feedback on the Lead form.
frappe.ui.form.on("Lead", {
    refresh(frm) {
        alphax_dq_render(frm);
        frm.add_custom_button(__("Check Data Quality"), () => alphax_dq_render(frm, true), __("AlphaX"));
    },
    onload_post_render(frm) {
        alphax_dq_bind(frm);
    },
});

function alphax_dq_bind(frm) {
    // Re-check as the user edits, debounced.
    if (frm.__alphax_dq_bound) return;
    frm.__alphax_dq_bound = true;
    frm.$wrapper.on("change awesomplete-selectcomplete", "input, select, textarea", () => {
        clearTimeout(frm.__alphax_dq_t);
        frm.__alphax_dq_t = setTimeout(() => alphax_dq_render(frm), 500);
    });
}

function alphax_dq_render(frm, verbose) {
    if (frm.is_new() && !verbose && !frm.doc.lead_name) return;
    frappe.call({
        method: "alphax_crm.crm.data_quality.check",
        args: { doc: frm.doc },
        callback: (r) => {
            const d = r.message;
            if (!d) return;
            const color = d.issues.length ? "red" : (d.warnings.length ? "orange" : "green");
            const label = `Data Quality: ${d.score}%` +
                (d.issues.length ? ` — ${d.issues.length} to fix` : "") +
                (d.warnings.length ? ` — ${d.warnings.length} recommended` : "");
            frm.dashboard.clear_headline();
            frm.dashboard.set_headline_alert(label, color);

            // Highlight offending fields.
            (frm.__alphax_dq_marked || []).forEach((f) => frm.set_df_property(f, "description", ""));
            frm.__alphax_dq_marked = [];
            d.issues.concat(d.warnings).forEach((it) => {
                if (frm.fields_dict[it.field]) {
                    frm.set_df_property(it.field, "description",
                        `<span style="color:${it.kind === "invalid" ? "#b91c1c" : "#b45309"}">⚠ ${frappe.utils.escape_html(it.reason)}</span>`);
                    frm.__alphax_dq_marked.push(it.field);
                }
            });

            if (verbose) {
                const lines = d.issues.map((i) => `• <b>${frappe.utils.escape_html(i.label)}</b> ${frappe.utils.escape_html(i.reason)}`)
                    .concat(d.warnings.map((w) => `• ${frappe.utils.escape_html(w.label)} ${frappe.utils.escape_html(w.reason)} <i>(recommended)</i>`));
                frappe.msgprint({
                    title: __("Data Quality — {0}%", [d.score]),
                    message: lines.length ? lines.join("<br>") : __("All configured checks passed."),
                    indicator: color,
                });
            }
        },
    });
}
