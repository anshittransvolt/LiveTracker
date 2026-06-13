import { getDisplayVehicleNumber } from './vehicle_mapping.js';

(function () {
    let lastAlertId = 0;
    let pollInterval = 10000; // 10 seconds
    let isRunning = false;

    // Configure Toastr
    if (typeof toastr !== "undefined") {
        toastr.options = {
            closeButton: true,
            newestOnTop: true,
            progressBar: true,
            positionClass: "toast-top-right",
            preventDuplicates: true,
            timeOut: "15000",
            extendedTimeOut: "5000",
            showMethod: "fadeIn",
            hideMethod: "fadeOut"
        };
        // console.log("Toastr configured successfully");
    } else {
        console.error("Toastr is not loaded");
    }

    function formatAlertTitle(alertType, vehicleNo) {
        const typeMap = {
            charging_overrun: "Charging Alert",
            unplanned_stop_outside_geofence: "Unplanned Stop",
            data_feed_gap: "Data Feed Gap",
            tare_weight_overrun: "Weighing Alert",
            gross_weight_overrun: "Weighing Alert",
            loading_overrun: "Loading Alert",
            tarpaulin_overrun: "Tarpaulin Alert",
            maha_border_dwell: "Border Alert",
            unloading_overrun: "Unloading Alert",
            gate_in_manawar: "Gate Entry",
            gate_out_manawar: "Gate Exit",
            transit_sla_violation: "Transit SLA Alert",
            soc_100_stuck: "Battery Alert"
        };

        return typeMap[alertType] || vehicleNo;
    }

    function getToastrMethod(alertType) {
        if (
            alertType.includes("overrun") ||
            alertType.includes("dwell") ||
            alertType.includes("gap") ||
            alertType.includes("stuck")
        ) {
            return "warning";
        }

        if (alertType.includes("unplanned") || alertType.includes("violation")) {
            return "error";
        }

        if (alertType.includes("gate_in") || alertType.includes("gate_out")) {
            return "info";
        }

        if (alertType.includes("transit")) {
            return "warning";
        }

        return "info";
    }

    function displayAlert(alert) {
        if (typeof toastr === "undefined") {
            console.warn("Toastr unavailable:", alert.text);
            return;
        }
        
        // Map trolley to truck number for display
        const displayVehicleNo = getDisplayVehicleNumber(alert.vehicle_no);

        const title = formatAlertTitle(alert.alert_type, displayVehicleNo);
        let message = alert.text || "No details available";

        if (alert.soc !== undefined && alert.soc !== null) {
            message += `\nSOC: ${alert.soc}%`;
        }
        if (alert.geofence_name) {
            message += `\nLocation: ${alert.geofence_name}`;
        }

        const method = getToastrMethod(alert.alert_type);
        const timeout = method === "error" ? 20000 : 15000;

        toastr[method](message, title, { timeOut: timeout });
        // console.log(`Alert displayed: [${alert.alert_type}] ${displayVehicleNo}`);
    }

    async function fetchAlerts() {
        try {
            const response = await fetch("/livetracker/api/alerts/?minutes=2");

            if (!response.ok) {
                console.error("HTTP error:", response.status);
                return;
            }

            const data = await response.json();

            if (data.success && data.alerts && data.alerts.length > 0) {
                const newAlerts = data.alerts.filter((alert) => alert.id > lastAlertId);

                if (newAlerts.length > 0) {
                    // console.log(`Found ${newAlerts.length} new alerts`);

                    lastAlertId = Math.max(...newAlerts.map((a) => a.id));

                    newAlerts.forEach((alert) => displayAlert(alert));
                }
            }
        } catch (err) {
            console.error("Error fetching alerts:", err);
        }
    }

    function startMonitoring() {
        if (isRunning) {
            console.warn("Alert monitoring already running");
            return;
        }

        // console.log("Starting alert monitoring...");
        isRunning = true;

        fetchAlerts();
        setInterval(fetchAlerts, pollInterval);
    }

    // Start monitoring when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", startMonitoring);
    } else {
        startMonitoring();
    }

    // Debug access
    window.alertMonitor = {
        fetchAlerts: fetchAlerts,
        lastAlertId: () => lastAlertId,
        isRunning: () => isRunning
    };
})();
