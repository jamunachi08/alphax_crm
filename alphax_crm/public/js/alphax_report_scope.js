// AlphaX CRM — common report filters (crm/report_scope.py).
// Each report's .js ends with alphax_report_scope("<Report Name>", { doctype: "<what it counts>" }).
// Adds, after the report's own filters: Lead Stage, Lead Status, the report doctype's Status,
// Date Based On + From / To, and the extra fields set in AlphaX CRM Settings > 9.2.
(function () {
    const SKIP_TYPES = ["Date", "Datetime"];

    function pick_doctype(row, doctype) {
        const metas = row.metas || {};
        if (row.document_type) {
            return metas[row.document_type] && [doctype, "Lead"].includes(row.document_type) ? row.document_type : null;
        }
        if (metas[doctype]) return doctype;
        return metas.Lead ? "Lead" : null;
    }

    function options_list(options) {
        return (txt) => (options || [])
            .filter((o) => !txt || String(o).toLowerCase().includes(String(txt).toLowerCase()))
            .map((o) => ({ value: o, description: "" }));
    }

    window.alphax_report_scope = function (report_name, opts) {
        opts = opts || {};
        const cfg = frappe.boot && frappe.boot.alphax_report_scope;
        const report = frappe.query_reports[report_name];
        if (!cfg || !report) return;
        report.filters = report.filters || [];
        const doctype = opts.doctype || "Lead";
        const skip = new Set(opts.skip || []);
        const have = new Set(report.filters.map((f) => f.fieldname));
        const add = (df) => {
            if (have.has(df.fieldname) || skip.has(df.fieldname)) return;
            report.filters.push(df);
            have.add(df.fieldname);
        };
        const multi = (fieldname, label, options) => {
            if (options && options.length) add({ fieldname, label, fieldtype: "MultiSelectList", get_data: options_list(options) });
        };
        const dt_cfg = (cfg.doctypes || {})[doctype] || {};

        if (cfg.status) {
            multi("ax_lead_stage", __("Lead Stage"), cfg.lead_stage_options);
            multi("ax_lead_status", __("Lead Status"), cfg.lead_status_options);
            if (doctype !== "Lead") multi("ax_status", __("{0} Status", [__(dt_cfg.label || doctype)]), dt_cfg.status_options);
        }
        if (cfg.dates) {
            add({ fieldname: "ax_date_field", label: __("Date Based On"), fieldtype: "Select", default: "creation",
                  options: dt_cfg.date_fields || [{ value: "creation", label: __("Created On") }] });
            add({ fieldname: "ax_from_date", label: __("From (Date Based On)"), fieldtype: "Date" });
            add({ fieldname: "ax_to_date", label: __("To (Date Based On)"), fieldtype: "Date" });
        }
        (cfg.fields || []).forEach((row) => {
            if (row.report && row.report !== report_name) return;
            const dt = pick_doctype(row, doctype);
            if (!dt) return;
            const m = row.metas[dt];
            if (!m || SKIP_TYPES.includes(m.fieldtype)) return;
            if (dt === doctype && have.has(row.fieldname)) return; // the report already filters this field
            const df = { fieldname: `axf_${cfg.slug[dt]}__${row.fieldname}`,
                         label: dt === doctype ? m.label : `${m.label} (${__(dt)})` };
            if (m.fieldtype === "Link") Object.assign(df, { fieldtype: "Link", options: m.options });
            else if (m.fieldtype === "Select") Object.assign(df, { fieldtype: "Select", options: "\n" + (m.options || "") });
            else if (m.fieldtype === "Check") Object.assign(df, { fieldtype: "Select", options: "\nYes\nNo" });
            else df.fieldtype = "Data";
            add(df);
        });
    };
})();
