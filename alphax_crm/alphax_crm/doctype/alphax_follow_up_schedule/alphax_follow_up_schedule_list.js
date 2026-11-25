frappe.listview_settings["AlphaX Follow-up Schedule"] = {
    add_fields: ["status", "start_datetime", "platform"],
    get_indicator(doc) {
        if (doc.status === "Cancelled") return [__("Cancelled"), "gray", "status,=,Cancelled"];
        if (doc.status === "Completed") return [__("Completed"), "green", "status,=,Completed"];
        if (doc.start_datetime && moment(doc.start_datetime).isBefore(moment())) return [__("Overdue"), "orange", "status,=,Scheduled"];
        return [__("Scheduled"), "blue", "status,=,Scheduled"];
    },
    onload(list) {
        list.page.add_inner_button(__("Calendar"), () => frappe.set_route("List", "AlphaX Follow-up Schedule", "Calendar", "default"));
    },
};
