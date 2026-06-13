// livetracker/static/livetracker/js/alert_monitor.js
// Monitors for new alerts and displays them using toastr

import { getDisplayVehicleNumber } from './vehicle_mapping.js';

class AlertMonitor {
    constructor(pollInterval = 60000) { // Poll every 60 seconds (increased from 30s to reduce conflicts with LiveToastManager)
        this.pollInterval = pollInterval;
        this.lastAlertId = 0;
        this.isRunning = false;
        this.intervalId = null;
        this.shownAlerts = new Set(); // Track alerts we've already shown to prevent duplicates
        this.shownContentHashes = new Set(); // Track content hashes to prevent duplicate alerts with different IDs
        this.maxShownHistory = 100; // Keep track of last 100 alerts to prevent re-showing
        
        // Configure toastr
        if (typeof toastr !== 'undefined') {
            toastr.options = {
                "closeButton": true,
                "debug": false,
                "newestOnTop": true,
                "progressBar": true,
                "positionClass": "toast-top-right",
                "preventDuplicates": true, // Prevent duplicate toasts
                "onclick": null,
                "showDuration": "300",
                "hideDuration": "1000",
                "timeOut": "10000",
                "extendedTimeOut": "3000",
                "showEasing": "swing",
                "hideEasing": "linear",
                "showMethod": "fadeIn",
                "hideMethod": "fadeOut"
            };
        }
    }

    /**
     * Start monitoring for alerts
     */
    start() {
        if (this.isRunning) {
            console.warn('Alert monitor is already running');
            return;
        }

        // console.log('Starting alert monitor...');
        this.isRunning = true;
        
        // Fetch alerts immediately
        this.fetchAlerts();
        
        // Then poll at intervals
        this.intervalId = setInterval(() => {
            this.fetchAlerts();
        }, this.pollInterval);
    }

    /**
     * Stop monitoring for alerts
     */
    stop() {
        if (!this.isRunning) {
            console.warn('Alert monitor is not running');
            return;
        }

        // console.log('Stopping alert monitor...');
        this.isRunning = false;
        
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
    }

    /**
     * Generate a unique content hash for deduplication
     */
    getContentHash(alert) {
        // Create hash from alert_type + vehicle_no + text
        const content = `${alert.alert_type}|${alert.vehicle_no}|${alert.text}`;
        return this.simpleHash(content);
    }

    /**
     * Simple hash function
     */
    simpleHash(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32-bit integer
        }
        return hash;
    }

    /**
     * Fetch recent alerts from the API
     */
    async fetchAlerts() {
        try {
            const response = await fetch('/livetracker/api/alerts/?minutes=1');
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.success && data.alerts && data.alerts.length > 0) {
                // Process new alerts (filter by lastAlertId AND not already shown by ID or content)
                const newAlerts = data.alerts.filter(alert => {
                    const contentHash = this.getContentHash(alert);
                    return alert.id > this.lastAlertId && 
                           !this.shownAlerts.has(alert.id) &&
                           !this.shownContentHashes.has(contentHash);
                });
                
                if (newAlerts.length > 0) {
                    // console.log(`Received ${newAlerts.length} new alerts`);
                    
                    // Update lastAlertId to the highest ID
                    const maxId = Math.max(...newAlerts.map(a => a.id));
                    this.lastAlertId = maxId;
                    
                    // Display each alert and mark as shown
                    newAlerts.forEach(alert => {
                        this.displayAlert(alert);
                        this.shownAlerts.add(alert.id);
                        this.shownContentHashes.add(this.getContentHash(alert));
                    });
                    
                    // Cleanup old shown alerts if set gets too large
                    if (this.shownAlerts.size > this.maxShownHistory) {
                        const alertsArray = Array.from(this.shownAlerts);
                        const toRemove = alertsArray.slice(0, alertsArray.length - this.maxShownHistory);
                        toRemove.forEach(id => this.shownAlerts.delete(id));
                    }
                    
                    // Cleanup old content hashes (keep last 200)
                    if (this.shownContentHashes.size > 200) {
                        const hashArray = Array.from(this.shownContentHashes);
                        const toRemove = hashArray.slice(0, hashArray.length - 200);
                        toRemove.forEach(h => this.shownContentHashes.delete(h));
                    }
                }
            }
            
        } catch (error) {
            console.error('Error fetching alerts:', error);
        }
    }

    /**
     * Display an alert using toastr
     */
    displayAlert(alert) {
        if (typeof toastr === 'undefined') {
            console.warn('Toastr is not available. Alert:', alert.text);
            return;
        }

        // Determine alert level based on alert_type
        const alertType = alert.alert_type || 'info';
        let toastrMethod = 'info';
        
        // Map alert types to toastr methods
        if (alertType.includes('overrun') || alertType.includes('dwell') || 
            alertType.includes('gap') || alertType.includes('stuck')) {
            toastrMethod = 'warning';
        } else if (alertType.includes('unplanned') || alertType.includes('violation')) {
            toastrMethod = 'error';
        } else if (alertType.includes('gate_in') || alertType.includes('gate_out')) {
            toastrMethod = 'info';
        } else if (alertType.includes('transit')) {
            toastrMethod = 'warning';
        }

        // Format the alert message
        const title = this.formatAlertTitle(alert);
        const message = this.formatAlertMessage(alert);

        // Display using appropriate toastr method
        toastr[toastrMethod](message, title, {
            timeOut: alertType.includes('error') || alertType.includes('unplanned') ? 15000 : 10000,
            onclick: () => {
                this.handleAlertClick(alert);
            }
        });
        
        // Map vehicle number for console log
        const displayVehicleNo = getDisplayVehicleNumber(alert.vehicle_no);
        // console.log(`Alert displayed: ${alertType} - ${displayVehicleNo}`);
    }

    /**
     * Format alert title
     */
    formatAlertTitle(alert) {
        const typeMap = {
            'charging_overrun': '⚡ Charging Alert',
            'unplanned_stop_outside_geofence': '⚠️ Unplanned Stop',
            'data_feed_gap': '📡 Data Feed Gap',
            'tare_weight_overrun': '⚖️ Weighing Alert',
            'gross_weight_overrun': '⚖️ Weighing Alert',
            'loading_overrun': '📦 Loading Alert',
            'tarpaulin_overrun': '🎪 Tarpaulin Alert',
            'maha_border_dwell': '🚧 Border Alert',
            'unloading_overrun': '📦 Unloading Alert',
            'gate_in_manawar': '🚪 Gate Entry',
            'gate_out_manawar': '🚪 Gate Exit',
            'transit_sla_violation': '⏱️ Transit SLA Alert',
            'soc_100_stuck': '🔋 Battery Alert'
        };
        
        // Map trolley to truck number for display
        const displayVehicleNo = getDisplayVehicleNumber(alert.vehicle_no);

        return typeMap[alert.alert_type] || `🔔 ${displayVehicleNo}`;
    }

    /**
     * Format alert message
     */
    formatAlertMessage(alert) {
        let msg = alert.text || 'No details available';
        
        // Add location if available
        if (alert.gps_location) {
            msg += `\n📍 Location: ${alert.gps_location}`;
        }
        
        // Add SOC if available
        if (alert.soc !== null && alert.soc !== undefined) {
            msg += `\n🔋 SOC: ${alert.soc}%`;
        }

        // Add geofence if available
        if (alert.geofence_name) {
            msg += `\n📌 Geofence: ${alert.geofence_name}`;
        }

        return msg;
    }

    /**
     * Handle alert click (optional - can be used to show more details)
     */
    handleAlertClick(alert) {
        // console.log('Alert clicked:', alert);
        
        // Optional: Show alert details in a modal or navigate to vehicle page
        if (alert.vehicle_no) {
            // You could navigate to the vehicle details page
            // window.location.href = `/livetracker/${alert.vehicle_no}/`;
        }
    }

    /**
     * Manually mark an alert as seen
     */
    async markAlertSeen(alertId) {
        try {
            const response = await fetch(`/livetracker/api/alerts/${alertId}/seen/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            // console.log(`Alert ${alertId} marked as seen:`, data);
            
            return data;
        } catch (error) {
            console.error('Error marking alert as seen:', error);
            return null;
        }
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AlertMonitor;
}

// Auto-start alert monitoring when page loads (if toastr is available)
if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', function() {
        // Create global instance with 60 second polling (slower than LiveToastManager's 10s to avoid conflicts)
        window.alertMonitor = new AlertMonitor(60000); // Poll every 60 seconds
        
        // Start monitoring automatically
        window.alertMonitor.start();
        
        // console.log('Alert monitoring initialized and started (60s interval)');
    });
}
