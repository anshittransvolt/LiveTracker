"""
alert.py: Main orchestration and service class for the alert system.

Data source: TWINS API via TwinsAPIAdapter (twins.transvolt.org/fetch_combined).
SmartFastAPI (smartfastapi.transvolt.org) has been removed — it is deprecated.

Key methods:
    - start_monitoring(): Starts periodic data fetching and alert processing
    - stop_monitoring(): Stops the monitoring loop
    - fetch_vehicle_data(): Retrieves latest vehicle points from TWINS API
    - process_vehicle_data(): Runs the alert processor and sends alerts
"""

import time
import logging
from threading import Thread
from typing import Optional, Dict, Any, List
from livetracker.alertService.alert_processor import process_batch
from livetracker.data_sources.twins_adapter import TwinsAPIAdapter


class alertService:
    def __init__(self, vendor: str = None, spv: str = None):
        """
        Initialize the alert service.

        Args:
            vendor: Vendor filter for TWINS API (e.g. 'intangles'). Defaults to
                    TWINS_VENDOR Django setting or 'iplt'.
            spv:    SPV filter for TWINS API (e.g. 'UMT'). Defaults to
                    TWINS_SPV Django setting or 'ultratech'.
        """
        self._vendor = vendor
        self._spv = spv
        self.is_running = False
        self.fetch_thread = None

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(__name__)

    def fetch_vehicle_data(self) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch the latest vehicle point for every vehicle from the TWINS API.

        Returns:
            List of records (one per vehicle, latest point only) in the format
            expected by alert_processor.process_batch(), or None on failure.
        """
        try:
            self.logger.info("Fetching vehicle data from TWINS API…")
            adapter = TwinsAPIAdapter()
            grouped = adapter.fetch_all_vehicles(
                vendor=self._vendor,
                spv=self._spv,
            )
            if not grouped:
                self.logger.warning("TWINS API returned no vehicles")
                return None

            # Extract the most-recent point for each vehicle
            records: List[Dict[str, Any]] = []
            for reg_no, vehicle in grouped.items():
                points = vehicle.get("points", [])
                if points:
                    records.append(points[0])  # already sorted newest-first

            self.logger.info(f"Fetched latest point for {len(records)} vehicles")
            return records

        except Exception as e:
            self.logger.error(f"Error fetching vehicle data from TWINS API: {e}", exc_info=True)
            return None

    def process_vehicle_data(self, data: List[Dict[str, Any]], spv: str = None):
        """
        Run the alert processor against a list of vehicle records.

        TwinsAPIAdapter already outputs records in the format process_batch()
        expects (vehicle_no, vehicle_id, gps_location, soc, vehicle_status,
        last_connected, driver_name), so no further transformation is needed.
        """
        if not data:
            self.logger.warning("No data to process")
            return

        try:
            alerts = process_batch(data, spv=spv)
            self.logger.info(f"Alert processor returned {len(alerts) if alerts else 0} alert(s)")
        except Exception as e:
            self.logger.error(f"Error processing vehicle data: {e}", exc_info=True)

    def start_monitoring(self):
        """
        Start monitoring vehicle data every 60 seconds
        """
        if self.is_running:
            self.logger.warning("Monitoring is already running")
            return

        self.is_running = True
        self.fetch_thread = Thread(target=self._monitoring_loop)
        self.fetch_thread.daemon = True
        self.fetch_thread.start()
        self.logger.info("Started vehicle data monitoring (60 second interval)")

    def _monitoring_loop(self):
        """
        Internal loop that fetches data every 60 seconds
        """
        while self.is_running:
            try:
                data = self.fetch_vehicle_data()

                if data:
                    self.process_vehicle_data(data, spv=self._spv)
                else:
                    self.logger.warning(
                        "Failed to fetch data, will retry in 60 seconds"
                    )

            except Exception as e:
                self.logger.error(f"Unexpected error in monitoring loop: {e}")

            # Wait for 60 seconds before next fetch
            time.sleep(60)

    def stop_monitoring(self):
        """
        Stop the monitoring loop
        """
        if self.is_running:
            self.is_running = False
            if self.fetch_thread:
                self.fetch_thread.join(timeout=5)
            self.logger.info("Stopped vehicle data monitoring")
        else:
            self.logger.warning("Monitoring is not running")
