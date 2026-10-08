// AlphaX BI Dashboard — one master screen pulling together the whole
// "AlphaX ... (BI)" report family (Lead Stage Tracker, Pipeline Aging, Lost
// Reason Breakdown, Quotation Value by Business Unit, Stage Conversion,
// Sales Person Performance, Source Performance) behind a single shared
// filter bar and a row of tabs, instead of opening each report on its own
// from the Report List one at a time.
//
// One frappe.call fetches every report's (summary/chart/table) in a single
// round trip (alphax_crm.api.bi_dashboard.get_bi_dashboard_data); switching
// tabs afterwards is pure client-side show/hide, no extra server call,
// same pattern AlphaX Executive Dashboard already uses for its own charts
// (frappe.Chart, already bundled in the desk).

const ALPHAX_BI_TABS = [
	["lead_stage_tracker", __("Lead Stage Tracker")],
	["pipeline_aging", __("Pipeline Aging")],
	["stage_conversion", __("Stage Conversion")],
	["lost_reason_breakdown", __("Lost Reason Breakdown")],
	["quotation_value_by_bu", __("Quotation Value by Business Unit")],
	["sales_person_performance", __("Sales Person Performance")],
	["source_performance", __("Source Performance")],
];

frappe.pages["alphax-bi-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("AlphaX BI Dashboard"),
		single_column: true,
	});

	const state = {
		as_of_date: frappe.datetime.get_today(),
		period_type: "Monthly",
		compare_mode: "None",
		years_back: "1",
		lead_owner: null,
		source: null,
		city: null,
		custom_business_lead_unit: null,
	};

	const reload = () => alphax_bi_dashboard_load(page, state);

	page.add_field({
		fieldname: "as_of_date",
		label: __("As Of Date"),
		fieldtype: "Date",
		default: state.as_of_date,
		change() {
			state.as_of_date = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "period_type",
		label: __("Period Type"),
		fieldtype: "Select",
		options: "Daily\nWeekly\nMonthly\nQuarterly\nHalf-Yearly\nYearly",
		default: state.period_type,
		change() {
			state.period_type = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "compare_mode",
		label: __("Compare Mode"),
		fieldtype: "Select",
		options: "None\nSame Period Last Year\nSame Quarter Last Year\nFull Last Year",
		default: state.compare_mode,
		change() {
			state.compare_mode = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "years_back",
		label: __("Years Back"),
		fieldtype: "Select",
		options: "1\n2\n3",
		default: state.years_back,
		change() {
			state.years_back = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "lead_owner",
		label: __("Sales Person"),
		fieldtype: "Link",
		options: "User",
		change() {
			state.lead_owner = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "source",
		label: __("Source"),
		fieldtype: "Link",
		options: "Lead Source",
		change() {
			state.source = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "city",
		label: __("City"),
		fieldtype: "Data",
		change() {
			state.city = this.get_value();
			reload();
		},
	});
	page.add_field({
		fieldname: "custom_business_lead_unit",
		label: __("Business Unit"),
		fieldtype: "Link",
		options: "AlphaX Business Unit",
		change() {
			state.custom_business_lead_unit = this.get_value();
			reload();
		},
	});
	page.set_primary_action(__("Refresh"), reload, "refresh");

	let tabs_html = `<div class="alphax-bi-tabbar">`;
	ALPHAX_BI_TABS.forEach(([id, label], i) => {
		tabs_html += `<div class="alphax-bi-tab${i === 0 ? " active" : ""}" data-tab="${id}">${frappe.utils.escape_html(label)}</div>`;
	});
	tabs_html += `</div>`;

	let panes_html = "";
	ALPHAX_BI_TABS.forEach(([id], i) => {
		panes_html += `
			<div class="alphax-bi-pane" id="alphax-bi-pane-${id}" style="display:${i === 0 ? "block" : "none"};">
				<div id="alphax-bi-kpis-${id}" class="alphax-bi-kpis"></div>
				<div class="alphax-dash-card" style="margin-bottom:16px;">
					<div class="alphax-dash-card-title">${__("Chart")}</div>
					<div id="alphax-bi-chart-${id}"></div>
				</div>
				<div class="alphax-dash-card">
					<div class="alphax-dash-card-title">${__("Detail")}</div>
					<div id="alphax-bi-table-${id}"></div>
				</div>
			</div>`;
	});

	page.main.html(`
		<div id="alphax-bi-root" style="padding: 4px 2px 24px;">
			${tabs_html}
			<div id="alphax-bi-message" class="text-muted small" style="margin: 10px 2px 16px;"></div>
			${panes_html}
		</div>
		<style>
			.alphax-dash-card {
				background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d1d8dd);
				border-radius: 10px; padding: 16px;
			}
			.alphax-dash-card-title { font-weight: 600; margin-bottom: 10px; font-size: 13px; color: var(--text-muted, #8d99a6); text-transform: uppercase; letter-spacing: .03em; }
			.alphax-bi-tabbar { display:flex; flex-wrap:wrap; gap:6px; border-bottom: 1px solid var(--border-color, #d1d8dd); margin-bottom: 4px; }
			.alphax-bi-tab {
				padding: 8px 14px; cursor: pointer; font-size: 13px; font-weight: 500;
				color: var(--text-muted, #8d99a6); border-bottom: 2px solid transparent;
			}
			.alphax-bi-tab:hover { color: var(--text-color, #1a1a1a); }
			.alphax-bi-tab.active { color: var(--primary, #2490ef); border-bottom-color: var(--primary, #2490ef); }
			.alphax-bi-kpis { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin: 16px 0; }
			.alphax-kpi { border-radius: 10px; padding: 16px; color: #fff; background: linear-gradient(135deg, #2490ef, #1b6fc9); }
			.alphax-kpi.green { background: linear-gradient(135deg, #2ecc71, #22a35b); }
			.alphax-kpi.red { background: linear-gradient(135deg, #e24c4c, #b93030); }
			.alphax-kpi.grey { background: linear-gradient(135deg, #8d99a6, #6b7680); }
			.alphax-kpi .alphax-kpi-value { font-size: 22px; font-weight: 700; line-height: 1.2; }
			.alphax-kpi .alphax-kpi-label { font-size: 12px; opacity: .85; margin-top: 4px; }
			.alphax-bi-table { width:100%; font-size: 13px; border-collapse: collapse; }
			.alphax-bi-table th, .alphax-bi-table td { padding: 6px 10px; border-bottom: 1px solid var(--border-color, #eaeef0); text-align: left; }
			.alphax-bi-table th { color: var(--text-muted, #8d99a6); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .02em; }
		</style>
	`);

	$(wrapper).on("click", ".alphax-bi-tab", function () {
		const tab = $(this).data("tab");
		$(wrapper).find(".alphax-bi-tab").removeClass("active");
		$(this).addClass("active");
		$(wrapper).find(".alphax-bi-pane").hide();
		$(wrapper).find(`#alphax-bi-pane-${tab}`).show();
	});

	reload();
};

function alphax_bi_dashboard_load(page, state) {
	frappe.call({
		method: "alphax_crm.api.bi_dashboard.get_bi_dashboard_data",
		args: state,
		freeze: true,
		callback: (r) => {
			const data = r.message;
			if (!data) return;
			alphax_bi_dashboard_render(data);
		},
		error: () => {
			$("#alphax-bi-root").html(
				`<div class="text-muted" style="padding: 40px; text-align:center;">${__("Could not load the dashboard. You may need the Sales User, Sales Manager or System Manager role.")}</div>`
			);
		},
	});
}

function alphax_bi_dashboard_render(data) {
	const messages = [];
	ALPHAX_BI_TABS.forEach(([id]) => {
		const tab = data[id];
		if (!tab) return;
		if (tab.error) {
			$(`#alphax-bi-kpis-${id}`).empty();
			$(`#alphax-bi-chart-${id}`).html(`<div class="text-muted small" style="padding:20px 0; text-align:center;">${frappe.utils.escape_html(tab.error)}</div>`);
			$(`#alphax-bi-table-${id}`).empty();
			return;
		}
		if (tab.message) messages.push(`${tab.label}: ${tab.message}`);
		alphax_bi_render_kpis(`alphax-bi-kpis-${id}`, tab.summary || []);
		alphax_bi_render_chart(`alphax-bi-chart-${id}`, tab.chart);
		alphax_bi_render_table(`alphax-bi-table-${id}`, tab.columns || [], tab.data || []);
	});
	// Keep the message strip short -- the active tab's own message is what
	// matters most, so show just that one plus a hint the others have more.
	const active_id = $(".alphax-bi-tab.active").data("tab") || ALPHAX_BI_TABS[0][0];
	const active_tab = data[active_id];
	$("#alphax-bi-message").text((active_tab && active_tab.message) || "");
}

function alphax_bi_render_kpis(el_id, summary) {
	const $el = $(`#${el_id}`).empty();
	summary.forEach((k) => {
		const value = k.datatype === "Currency" ? format_currency(k.value) : k.value;
		const cls = k.indicator === "green" ? "green" : k.indicator === "red" ? "red" : k.indicator === "blue" ? "" : "grey";
		$el.append(`
			<div class="alphax-kpi ${cls}">
				<div class="alphax-kpi-value">${frappe.utils.escape_html(String(value))}</div>
				<div class="alphax-kpi-label">${frappe.utils.escape_html(k.label)}</div>
			</div>
		`);
	});
}

function alphax_bi_render_chart(el_id, chart) {
	const el = document.getElementById(el_id);
	if (!el) return;
	el.innerHTML = "";
	if (!chart || !chart.data || !chart.data.labels || !chart.data.labels.length) {
		el.innerHTML = `<div class="text-muted small" style="padding:30px 0; text-align:center;">${__("No data for this filter selection.")}</div>`;
		return;
	}
	new frappe.Chart(el, {
		data: chart.data,
		type: chart.type || "bar",
		height: 240,
		colors: ["#2490ef", "#2ecc71", "#e24c4c"],
	});
}

function alphax_bi_format_cell(value, col) {
	if (value === null || value === undefined || value === "") return "<span class=\"text-muted\">—</span>";
	const ft = col.fieldtype;
	if (ft === "Currency") return format_currency(value);
	if (ft === "Percent") return `${value}%`;
	if (ft === "Float") return typeof value === "number" ? value.toFixed(col.precision || 1) : frappe.utils.escape_html(String(value));
	return frappe.utils.escape_html(String(value));
}

function alphax_bi_render_table(el_id, columns, data) {
	const el = document.getElementById(el_id);
	if (!el) return;
	if (!data.length) {
		el.innerHTML = `<div class="text-muted small" style="padding:20px 0; text-align:center;">${__("No data for this filter selection.")}</div>`;
		return;
	}
	let html = '<div style="overflow-x:auto;"><table class="alphax-bi-table"><thead><tr>';
	columns.forEach((c) => {
		html += `<th>${frappe.utils.escape_html(c.label)}</th>`;
	});
	html += "</tr></thead><tbody>";
	data.forEach((row) => {
		html += "<tr>";
		columns.forEach((c) => {
			html += `<td>${alphax_bi_format_cell(row[c.fieldname], c)}</td>`;
		});
		html += "</tr>";
	});
	html += "</tbody></table></div>";
	el.innerHTML = html;
}
