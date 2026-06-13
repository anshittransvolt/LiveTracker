"""
Incremental Trip Orchestrator
==============================
Processes telemetry one day at a time, carrying forward the raw rows of any
in-progress trip across day boundaries.

How it works
------------
1. For each day D in [start_date, end_date]:
     For each vehicle:
       a. Load VehicleTripState for (vehicle, D-1).  This contains the raw
          telemetry rows accumulated since the vehicle's last Manawar entry
          that has not yet produced a completed trip.
       b. Fetch telemetry for day D (single-day, per-vehicle API call).
       c. Concatenate accumulated rows + day D rows (deduplicated by timestamp).
       d. Run TripCalculator.calculate_trips() on the combined slice.
       e. Any completed trips are saved to DB.
       f. Determine carry-over rows for day D+1:
            - If trips completed → keep rows from last trip's M2 (return-
              Manawar) entry timestamp onwards.
            - If no trips completed → keep rows from the *last* Manawar entry
              in the combined data (trims stale data; prevents unbounded growth).
            - If no Manawar in remaining data at all → keep all remaining rows
              (vehicle is en-route and carry must not be dropped mid-trip).
       g. Save VehicleTripState(vehicle, D, carry_over_rows).

Benefits over the old chunked approach
---------------------------------------
* Memory is bounded: accumulated rows cover ~1-3 days of a single trip, not the
  entire requested date range.
* No separate "smart lookback" pass: the carry-over naturally handles trips that
  start before the requested start_date (as long as the state was seeded for the
  day before start_date, or the vehicle visits Manawar on day 1).
* API calls: one call per vehicle per day (same count as before for single-vehicle
  requests, but each payload is much smaller).
"""

import json
import logging
import gc
from datetime import date, timedelta
from typing import List, Dict, Any, Optional

import pandas as pd

from ..models import VehicleTripState, CalculatedTrip
from .trip_calculator_service import TripCalculator
from .geofence_processor import GeofenceProcessor
from .manual_entry_merger import ManualEntryMerger
from .data_source_client import fetch_telemetry_range

logger = logging.getLogger(__name__)


class IncrementalTripOrchestrator:
    """Day-by-day, stateful trip calculation."""

    def __init__(self):
        self.trip_calculator = TripCalculator()
        self.geofence_processor = GeofenceProcessor()
        self.merger = ManualEntryMerger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_date_range(
        self,
        start_date: date,
        end_date: date,
        vehicle_list: List[str],
        save_to_db: bool = True,
        skip_summary_rebuild: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Process [start_date, end_date] day-by-day for the given vehicles.

        Args:
            start_date:           First day to process (inclusive).
            end_date:             Last day to process (inclusive).
            vehicle_list:         Registration numbers to process.
            save_to_db:           If True, save completed trips to mis_calculated_trip
                                  immediately as each day is processed (incremental).
            skip_summary_rebuild: If True (and save_to_db=True), skip rebuilding
                                  TripPerformanceSummary after each save batch.
                                  Use when the caller will do a bulk rebuild at the end.

        Returns:
            Flat list of all completed trip dicts found across the date range.
        """
        if not vehicle_list:
            logger.warning("No vehicles provided to IncrementalTripOrchestrator")
            return []

        all_trips: List[Dict[str, Any]] = []
        current = start_date

        while current <= end_date:
            logger.info(f"[Incremental] Processing day {current} for {len(vehicle_list)} vehicle(s)")
            day_trips = self._process_day(current, vehicle_list)
            all_trips.extend(day_trips)

            if save_to_db and day_trips:
                if skip_summary_rebuild:
                    saved = self.merger._save_trips_no_summary(day_trips)
                else:
                    saved = self.merger.save_calculated_trips(day_trips)
                logger.info(f"[Incremental] Saved {saved} trips for {current}")

            gc.collect()
            current += timedelta(days=1)

        logger.info(f"[Incremental] Finished. Total trips found: {len(all_trips)}")
        return all_trips

    @staticmethod
    def get_known_vehicles() -> List[str]:
        """
        Return the full fleet vehicle list.  The authoritative source is
        KNOWN_FLEET in voltrack.vendor_config; DB state/trips are unioned in
        so any vehicles that appeared historically but were removed from the
        config file are still included.
        """
        try:
            from voltrack.vendor_config import KNOWN_FLEET
            fleet = list(KNOWN_FLEET)
        except Exception:
            fleet = []

        from_state = list(
            VehicleTripState.objects.values_list("vehicle_no", flat=True).distinct()
        )
        from_trips = list(
            CalculatedTrip.objects.values_list("vehicle_no", flat=True).distinct()
        )
        return list(set(fleet + from_state + from_trips))

    # ------------------------------------------------------------------
    # Day-level processing
    # ------------------------------------------------------------------

    def _process_day(
        self, target_date: date, vehicle_list: List[str]
    ) -> List[Dict[str, Any]]:
        """Process one calendar day for every vehicle in the list."""
        all_trips: List[Dict[str, Any]] = []

        for vehicle_no in vehicle_list:
            try:
                trips = self._process_vehicle_day(vehicle_no, target_date)
                all_trips.extend(trips)
            except Exception as exc:
                logger.error(
                    f"[Incremental] Error processing {vehicle_no} on {target_date}: {exc}",
                    exc_info=True,
                )
                # Carry the previous state forward so the chain is not broken.
                # Without this, tomorrow's prev_state lookup returns None and all
                # accumulated carry rows are permanently lost.
                try:
                    prev_state = VehicleTripState.objects.filter(
                        vehicle_no=vehicle_no,
                        state_date=target_date - timedelta(days=1),
                    ).first()
                    self._carry_state_forward(vehicle_no, target_date, prev_state)
                except Exception as carry_exc:
                    logger.error(
                        f"[Incremental] Failed to carry state forward for {vehicle_no} "
                        f"on {target_date} after error: {carry_exc}"
                    )

        return all_trips

    def _process_vehicle_day(
        self, vehicle_no: str, target_date: date
    ) -> List[Dict[str, Any]]:
        """
        Core per-vehicle, per-day logic.

        Returns completed trip dicts (may be empty if the trip is still open).
        Side-effect: creates/updates VehicleTripState for (vehicle_no, target_date).
        """
        # 1. Load previous state
        prev_state = VehicleTripState.objects.filter(
            vehicle_no=vehicle_no,
            state_date=target_date - timedelta(days=1),
        ).first()

        # 2. Fetch today's telemetry (single day, single vehicle)
        day_df = fetch_telemetry_range(target_date, target_date, vehicle_no)
        logger.debug(
            f"[Incremental] {vehicle_no} / {target_date}: fetched {len(day_df)} rows"
        )

        # 3. Merge with accumulated rows from yesterday's state
        combined = self._merge_with_accumulated(day_df, prev_state)

        if combined.empty:
            # Nothing to process; carry previous state forward unchanged
            self._carry_state_forward(vehicle_no, target_date, prev_state)
            return []

        # 4. Calculate trips on the combined slice
        logger.debug(
            f"[Incremental] {vehicle_no} / {target_date}: running calculate_trips on {len(combined)} rows"
        )
        trips = self.trip_calculator.calculate_trips(combined)
        logger.info(
            f"[Incremental] {vehicle_no} / {target_date}: {len(trips)} trip(s) completed"
        )

        # 5. Determine carry-over data for tomorrow
        carry_df = self._get_carry_over_rows(combined, trips)

        # 6. Persist state
        self._save_state(vehicle_no, target_date, carry_df)

        return trips

    # ------------------------------------------------------------------
    # Helpers: data merging
    # ------------------------------------------------------------------

    def _merge_with_accumulated(
        self,
        day_df: pd.DataFrame,
        prev_state: Optional[VehicleTripState],
    ) -> pd.DataFrame:
        """
        Prepend the accumulated rows from the previous state to today's data.
        Deduplicates on `last_connected` and sorts chronologically.
        """
        if prev_state is None:
            return day_df

        raw_json = prev_state.accumulated_rows_json
        if not raw_json or raw_json == "[]":
            return day_df

        try:
            acc_records = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                f"[Incremental] Could not parse accumulated_rows_json for "
                f"{prev_state.vehicle_no} / {prev_state.state_date}"
            )
            return day_df

        if not acc_records:
            return day_df

        acc_df = pd.DataFrame(acc_records)

        # Re-parse timestamps (stored as ISO strings in JSON)
        for ts_col in ("last_connected", "gps_time"):
            if ts_col in acc_df.columns:
                acc_df[ts_col] = pd.to_datetime(acc_df[ts_col], utc=True, errors="coerce")

        if day_df.empty:
            return acc_df

        combined = pd.concat([acc_df, day_df], ignore_index=True)
        combined = (
            combined.drop_duplicates(subset=["last_connected"])
            .sort_values("last_connected")
            .reset_index(drop=True)
        )
        return combined

    # ------------------------------------------------------------------
    # Helpers: carry-over computation
    # ------------------------------------------------------------------

    def _get_carry_over_rows(
        self,
        raw_df: pd.DataFrame,
        trips: List[Dict[str, Any]],
    ) -> pd.DataFrame:
        """
        Decide which raw rows should carry forward to the next day.

        Logic:
          1. If trips were completed, start from the last trip's M2 (return-
             Manawar) entry timestamp — these rows belong to the potential
             *next* trip.
          2. In whatever remains, trim to the *last* time the vehicle entered
             Manawar (continuous entry boundary).  This prevents unlimited
             accumulation if a vehicle is parked at Manawar for multiple
             days without completing a trip.
          3. If no Manawar is found in the remaining data, keep everything —
             the vehicle is mid-trip (between M1 and M2) and we must not drop
             data that is needed to close the trip later.
        """
        if raw_df.empty:
            return pd.DataFrame()

        # ---- Step 1: determine cutoff from last completed trip ----
        cutoff_ts = None
        if trips:
            for t in trips:
                ts = t.get("dhar_reach_time")  # M2 start_ts (vehicle back at Manawar)
                if ts is not None:
                    ts = pd.Timestamp(ts)
                    if not ts.tzinfo:
                        ts = ts.tz_localize("UTC")
                    if cutoff_ts is None or ts > cutoff_ts:
                        cutoff_ts = ts

        if cutoff_ts is not None:
            carry = raw_df[raw_df["last_connected"] >= cutoff_ts].copy()
        else:
            carry = raw_df.copy()

        if carry.empty:
            return carry

        # ---- Step 2: trim to last Manawar entry ----
        carry = self._trim_to_last_manawar(carry)
        return carry

    def _trim_to_last_manawar(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """
        Keep only rows from the last time the vehicle *entered* a Manawar
        geofence.  If no Manawar row exists in raw_df, return raw_df unchanged
        (vehicle is en-route between Manawar → Julwaniya/Dhule → Manawar and
        we must not discard the trip-in-progress data).
        """
        if raw_df.empty:
            return raw_df

        try:
            processed = self.geofence_processor.process_telemetry(raw_df.copy())
        except Exception as exc:
            logger.warning(f"[Incremental] geofence processing failed in trim: {exc}")
            return raw_df

        manawar_mask = processed["cluster"] == "Manawar"

        if not manawar_mask.any():
            # No Manawar — vehicle is en-route; keep everything
            return raw_df

        # Find the start of the *current continuous Manawar stay* by locating
        # the last row where the cluster was NOT Manawar, then taking everything
        # after that point.  This correctly handles sub-fence oscillation: if the
        # vehicle drifts between Manawar sub-fences during a long charging stop,
        # each sub-fence crossing still belongs to the same stay — we must not
        # cut to the most recent sub-fence entry and discard earlier charging rows.
        non_manawar_mask = ~manawar_mask
        if non_manawar_mask.any():
            # Index (positional) of the last non-Manawar row
            last_non_manawar_pos = processed.index[non_manawar_mask][-1]
            # Take everything strictly after it
            rows_after = processed.loc[last_non_manawar_pos + 1:]
            if rows_after.empty:
                # Tail of data is non-Manawar; vehicle is en-route — keep all
                return raw_df
            stay_start_ts = rows_after.iloc[0]["last_connected"]
            return raw_df[raw_df["last_connected"] >= stay_start_ts].copy()

        # All rows are Manawar (no non-Manawar row at all) — keep all
        return raw_df

    # ------------------------------------------------------------------
    # Helpers: state persistence
    # ------------------------------------------------------------------

    def _save_state(
        self,
        vehicle_no: str,
        state_date: date,
        carry_df: pd.DataFrame,
    ) -> None:
        """Persist VehicleTripState for (vehicle_no, state_date)."""
        if carry_df.empty:
            rows_json = "[]"
            last_cluster = None
            last_ts = None
            rows_count = 0
        else:
            # Serialize — convert tz-aware datetimes to ISO strings
            save_df = carry_df.copy()
            for col in save_df.columns:
                if pd.api.types.is_datetime64_any_dtype(save_df[col]):
                    save_df[col] = save_df[col].astype(str)
            rows_json = save_df.to_json(orient="records")

            # Get last known cluster from the tail of carry data
            try:
                tail_proc = self.geofence_processor.process_telemetry(
                    carry_df.tail(20).copy()
                )
                last_cluster = (
                    tail_proc.iloc[-1]["cluster"] if not tail_proc.empty else None
                )
            except Exception:
                last_cluster = None

            last_ts = carry_df["last_connected"].max()
            rows_count = len(carry_df)

        VehicleTripState.objects.update_or_create(
            vehicle_no=vehicle_no,
            state_date=state_date,
            defaults={
                "accumulated_rows_json": rows_json,
                "last_cluster": last_cluster or "",
                "last_ts": last_ts,
                "rows_count": rows_count,
            },
        )
        logger.debug(
            f"[Incremental] Saved state: {vehicle_no} / {state_date} "
            f"({rows_count} carry rows, last_cluster={last_cluster})"
        )

    def _carry_state_forward(
        self,
        vehicle_no: str,
        target_date: date,
        prev_state: Optional[VehicleTripState],
    ) -> None:
        """
        When there is no data for a day, copy the previous state to today so
        tomorrow's lookup still finds the right carry-over rows.
        """
        if prev_state is None:
            return

        VehicleTripState.objects.update_or_create(
            vehicle_no=vehicle_no,
            state_date=target_date,
            defaults={
                "accumulated_rows_json": prev_state.accumulated_rows_json,
                "last_cluster": prev_state.last_cluster,
                "last_ts": prev_state.last_ts,
                "rows_count": prev_state.rows_count,
            },
        )
