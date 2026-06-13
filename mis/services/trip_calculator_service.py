"""
Trip Calculator Service
=======================
Core logic for calculating trip metrics from geofence visits.
Updated to support flexible route patterns with flow validation.
"""

import pandas as pd
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from .geofence_processor import GeofenceProcessor, haversine_m
from .geofence_config import BATTERY_CAPACITY_KWH

logger = logging.getLogger(__name__)


def seconds_to_hhmm(sec: float) -> str:
    """Convert seconds to HH:MM format."""
    if pd.isna(sec) or sec is None:
        return "00:00"
    total_minutes = int(round(sec / 60.0))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def charging_duration_sec(charging_intervals: pd.DataFrame, gap_tolerance_min: float = 90.0):
    """
    Sum actual charging time from intervals where is_charging=True.

    SOC is reported sparsely (~every 30-60 min), so only a handful of
    intervals have soc_next > soc even during a 5-hour charge.  Simply
    summing duration_s gives ~17 min; using the raw wall-clock span
    (first→last) can overcount when the vehicle stays at the fence after
    charging ends.

    Approach: group consecutive is_charging intervals where the gap between
    them is ≤ gap_tolerance_min (default 90 min, safely above the ~60-min
    SOC-update cadence).  Use the wall-clock span of each contiguous group
    and sum those spans.

    Returns:
        (total_sec, first_session_start, last_session_end)
        where first_session_start/last_session_end are pd.Timestamp or None.
    """
    if charging_intervals.empty:
        return 0.0, None, None

    sorted_df = charging_intervals.sort_values('start_ts').reset_index(drop=True)
    gap_tolerance_s = gap_tolerance_min * 60.0

    sessions = []  # list of (start, end) per contiguous group
    session_start = sorted_df.iloc[0]['start_ts']
    session_end = sorted_df.iloc[0]['end_ts']

    for _, row in sorted_df.iloc[1:].iterrows():
        gap_s = (row['start_ts'] - session_end).total_seconds()
        if gap_s <= gap_tolerance_s:
            if row['end_ts'] > session_end:
                session_end = row['end_ts']
        else:
            sessions.append((session_start, session_end))
            session_start = row['start_ts']
            session_end = row['end_ts']

    sessions.append((session_start, session_end))

    total_sec = sum((end - start).total_seconds() for start, end in sessions)
    return max(total_sec, 0.0), sessions[0][0], sessions[-1][1]


class TripCalculator:
    """Calculate trip metrics from telemetry intervals."""
    def __init__(self):
        self.geofence_processor = GeofenceProcessor()

    def calculate_trips(self, telemetry_df: pd.DataFrame) -> List[Dict[str, Any]]:
        import time
        import gc  # Garbage collection for memory management
        
        t_start = time.time()
        if telemetry_df.empty:
            logger.warning("No telemetry data provided")
            return []
        
        # Memory optimization: limit logging for large datasets
        num_vehicles = telemetry_df['vehicle_no'].nunique()
        num_records = len(telemetry_df)
        logger.info(f"Calculating trips for {num_vehicles} vehicles, {num_records} records")
        
        try:
            t_geofence = time.time()
            telemetry_df = self.geofence_processor.process_telemetry(telemetry_df)
            logger.info(f"⏱️ Geofence processing: {time.time() - t_geofence:.2f}s")
            
            # Force garbage collection after geofence processing
            gc.collect()
            
            t_intervals = time.time()
            intervals_df = self.geofence_processor.build_intervals(telemetry_df)
            logger.info(f"⏱️ Interval building: {time.time() - t_intervals:.2f}s")
            
            if intervals_df.empty:
                logger.warning("No valid intervals found")
                return []
            
            # Clean up original telemetry_df to free memory
            del telemetry_df
            gc.collect()
            
            t_calc = time.time()
            all_trips = []
            vehicle_list = intervals_df['vehicle_no'].unique()
            
            # Reduce logging for production performance
            if num_vehicles <= 10:
                logger.info(f"Processing {len(vehicle_list)} vehicles: {', '.join(vehicle_list)}")
            else:
                logger.info(f"Processing {len(vehicle_list)} vehicles (names omitted for performance)")
            
            for idx, vehicle_no in enumerate(vehicle_list, 1):
                # Reduce per-vehicle logging for large fleets
                if num_vehicles <= 20:
                    logger.info(f"  [{idx}/{len(vehicle_list)}] Processing vehicle: {vehicle_no}")
                elif idx % 10 == 0:  # Log every 10th vehicle for large fleets
                    logger.info(f"  [{idx}/{len(vehicle_list)}] Processing batch...")
                
                try:
                    vehicle_intervals = intervals_df[intervals_df['vehicle_no'] == vehicle_no].reset_index(drop=True)
                    logger.debug(f"    {vehicle_no}: {len(vehicle_intervals)} intervals")
                    trips = self._calculate_trips_for_vehicle(vehicle_no, vehicle_intervals)
                    all_trips.extend(trips)
                    
                    # Memory cleanup for large datasets
                    if idx % 50 == 0:  # Cleanup every 50 vehicles
                        gc.collect()
                        
                except Exception as e:
                    import traceback
                    logger.error(f"Error processing vehicle {vehicle_no}: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    # Continue with other vehicles instead of failing completely
                    continue
            
            logger.info(f"⏱️ Trip calculation: {time.time() - t_calc:.2f}s")
            logger.info(f"✅ Calculated {len(all_trips)} complete trips in {time.time() - t_start:.2f}s total")
            
            return all_trips
            
        except Exception as e:
            logger.error(f"Critical error in calculate_trips: {str(e)}", exc_info=True)
            # Return empty list instead of crashing
            return []

    def _calculate_trips_for_vehicle(self, vehicle_no: str, intervals_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Calculate trips for a single vehicle with flexible route validation.
        Supports: M→J→D→M or M→J→D→[J/D shuttles]→M
        """
        trips = []
        visits = self.geofence_processor.build_cluster_visits(intervals_df)
        
        if len(visits) < 4:
            logger.info(f"Vehicle {vehicle_no}: Insufficient visits ({len(visits)}) for complete trip (need 4)")
            if visits:
                visit_sequence = " → ".join([v["cluster"] for v in visits])
                logger.info(f"  Visit sequence: {visit_sequence}")
            return trips
        
        visit_sequence = " → ".join([v["cluster"] for v in visits])
        logger.info(f"Vehicle {vehicle_no}: Total visit sequence: {visit_sequence}")
        
        i = 0
        trips_found = 0
        
        while i < len(visits):
            # Must start with Manawar
            if visits[i]["cluster"] != "Manawar":
                logger.debug(f"Vehicle {vehicle_no}: Position {i} is {visits[i]['cluster']}, not Manawar - skipping")
                i += 1
                continue
            
            logger.debug(f"Vehicle {vehicle_no}: Found Manawar at position {i}, attempting to build trip...")
            trip_start_idx = i
            j = i + 1
            
            # === PHASE 1: Forward Journey Validation (M → J → D) ===
            
            # Step 1: Next MUST be Julwaniya
            if j >= len(visits):
                logger.debug(f"Vehicle {vehicle_no}: No more visits after Manawar at position {i}")
                i += 1
                continue
            
            if visits[j]["cluster"] != "Julwaniya":
                logger.debug(f"Vehicle {vehicle_no}: Position {j} is {visits[j]['cluster']}, expected Julwaniya - not a valid trip start")
                i += 1
                continue
            
            logger.debug(f"Vehicle {vehicle_no}: ✓ Found Julwaniya at position {j}")
            julwaniya_fwd_idx = j
            j += 1
            
            # Step 2: Next MUST be Dhule
            if j >= len(visits):
                logger.debug(f"Vehicle {vehicle_no}: No more visits after Julwaniya at position {julwaniya_fwd_idx}")
                i += 1
                continue
            
            if visits[j]["cluster"] != "Dhule":
                logger.debug(f"Vehicle {vehicle_no}: Position {j} is {visits[j]['cluster']}, expected Dhule - not a valid trip")
                i += 1
                continue
            
            logger.debug(f"Vehicle {vehicle_no}: ✓ Found Dhule at position {j}")
            dhule_fwd_idx = j
            j += 1
            
            # === PHASE 2: Shuttle/Return Journey with Flow Validation ===
            
            logger.debug(f"Vehicle {vehicle_no}: Forward journey complete (M→J→D), now scanning for return journey...")
            last_location = "Dhule"
            shuttle_indices = []
            trip_end_idx = None
            
            while j < len(visits):
                current_location = visits[j]["cluster"]
                logger.debug(f"Vehicle {vehicle_no}: Position {j} = {current_location} (last was {last_location})")
                
                if current_location == "Manawar":
                    # Trip complete!
                    logger.debug(f"Vehicle {vehicle_no}: ✓ Found return Manawar at position {j} - TRIP COMPLETE!")
                    trip_end_idx = j
                    break
                
                elif current_location == "Julwaniya":
                    # Valid if coming from Dhule or Julwaniya
                    if last_location in ["Dhule", "Julwaniya"]:
                        logger.debug(f"Vehicle {vehicle_no}: ✓ Valid shuttle to Julwaniya")
                        shuttle_indices.append(j)
                        last_location = "Julwaniya"
                        j += 1
                    else:
                        # Invalid flow
                        logger.warning(f"Vehicle {vehicle_no}: ✗ Invalid flow - Julwaniya after {last_location} at position {j}")
                        break
                
                elif current_location == "Dhule":
                    # Valid if coming from Julwaniya or Dhule
                    if last_location in ["Dhule", "Julwaniya"]:
                        logger.debug(f"Vehicle {vehicle_no}: ✓ Valid shuttle to Dhule")
                        shuttle_indices.append(j)
                        last_location = "Dhule"
                        j += 1
                    else:
                        # Invalid flow
                        logger.warning(f"Vehicle {vehicle_no}: ✗ Invalid flow - Dhule after {last_location} at position {j}")
                        break
                
                else:
                    # Unknown location breaks the trip
                    logger.warning(f"Vehicle {vehicle_no}: ✗ Unknown location '{current_location}' at position {j} breaks trip flow")
                    break
            
            # Check if we found a complete trip
            if trip_end_idx is not None:
                # Build complete trip route for logging
                trip_route = f"M({trip_start_idx}) → J({julwaniya_fwd_idx}) → D({dhule_fwd_idx})"
                if shuttle_indices:
                    shuttle_route = " → ".join([f"{visits[idx]['cluster']}({idx})" for idx in shuttle_indices])
                    trip_route += f" → [{shuttle_route}]"
                trip_route += f" → M({trip_end_idx})"
                
                logger.info(f"Vehicle {vehicle_no}: ✅ COMPLETE TRIP #{trips_found + 1}: {trip_route}")
                
                # Compute trip metrics
                trip = self._compute_trip_metrics(
                    vehicle_no,
                    intervals_df,
                    M1=visits[trip_start_idx],
                    J=visits[julwaniya_fwd_idx],
                    D=visits[dhule_fwd_idx],
                    M2=visits[trip_end_idx],
                    shuttle_visits=[visits[idx] for idx in shuttle_indices]
                )
                trips.append(trip)
                trips_found += 1
                
                # Next trip starts from the return Manawar
                logger.debug(f"Vehicle {vehicle_no}: Moving to position {trip_end_idx} for next trip search")
                i = trip_end_idx
            else:
                # No complete trip found from this starting position
                logger.debug(f"Vehicle {vehicle_no}: No complete trip from Manawar at position {i}, moving to next position")
                i += 1
        
        if trips_found > 0:
            logger.info(f"Vehicle {vehicle_no}: ✅ Successfully found {trips_found} complete trip(s)")
        else:
            logger.warning(f"Vehicle {vehicle_no}: ⚠️ No complete trips found in {len(visits)} visits")
            logger.warning(f"  Expected pattern: Manawar→Julwaniya→Dhule→[shuttles]→Manawar")
            logger.warning(f"  Got: {visit_sequence}")
            
            # Debug file writing disabled for trip analysis
        
        return trips

    def _compute_trip_metrics(
        self,
        vehicle_no: str,
        intervals_df: pd.DataFrame,
        M1: Dict,
        J: Dict,
        D: Dict,
        M2: Dict,
        shuttle_visits: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Compute trip metrics with support for shuttle visits.
        shuttle_visits: List of visit dicts between forward Dhule and return Manawar
        """
        row = {}
        row["vehicle_no"] = vehicle_no
        
        if shuttle_visits is None:
            shuttle_visits = []
        
        # Helper to slice intervals for a visit
        def visit_slice(v):
            try:
                return intervals_df.loc[v["start_idx"]:v["end_idx"]].copy()
            except (KeyError, IndexError) as e:
                logger.warning(f"Error slicing intervals for {vehicle_no}: {e}")
                return pd.DataFrame()
        
        try:
            manawar1_df = visit_slice(M1)
            julwaniya_df = visit_slice(J)
            dhule_df = visit_slice(D)
            manawar2_df = visit_slice(M2)
        except Exception as e:
            logger.error(f"Error creating visit slices for {vehicle_no}: {e}")
            return {"vehicle_no": vehicle_no, "error": "Failed to process visit data"}
        
        # ========== MANAWAR BLOCK (M1) ==========
        manawar_in_ts = M1["start_ts"]
        manawar_charging_fence = manawar1_df[
            manawar1_df["geofence"] == "Manawar Charging Point"
        ] if not manawar1_df.empty else pd.DataFrame()
        # Use proper charging session detection instead of status=='Charging'
        sub_charge_M = manawar_charging_fence[
            manawar_charging_fence["is_charging"] == True
        ] if (not manawar_charging_fence.empty and "is_charging" in manawar_charging_fence.columns) else pd.DataFrame()
        manawar_loading_fence = manawar1_df[
            manawar1_df["geofence"] == "Manawar Loading Area"
        ] if not manawar1_df.empty else pd.DataFrame()
        exit_timestamps = [M1["end_ts"]]
        if not manawar_loading_fence.empty:
            exit_timestamps.append(manawar_loading_fence.iloc[-1]['end_ts'])
        if not manawar_charging_fence.empty:
            exit_timestamps.append(manawar_charging_fence.iloc[-1]['end_ts'])
        if not sub_charge_M.empty:
            exit_timestamps.append(sub_charge_M.iloc[-1]['end_ts'])
        manawar_out_ts = max(exit_timestamps)
        
        # Anchor log_date to vehicle out time (Manawar exit)
        row["log_date"] = manawar_out_ts.date()
        row["manawar_in_time"] = manawar_in_ts
        row["manawar_out_time"] = manawar_out_ts
        row["vehicle_out_time"] = manawar_out_ts
        
        # Start SOC = SOC when entering Manawar geofence (before any charging)
        if not manawar1_df.empty:
            try:
                first_row = manawar1_df.iloc[0]
                soc_val = first_row['soc'].item() if 'soc' in first_row.index and pd.notna(first_row['soc']) else None
                # If first row has no SOC, look ahead for first valid SOC value
                if soc_val is None and 'soc' in manawar1_df.columns:
                    valid_socs = manawar1_df[manawar1_df['soc'].notna()]['soc']
                    if not valid_socs.empty:
                        soc_val = valid_socs.iloc[0]
                row["start_soc"] = float(soc_val) if soc_val is not None else None
            except (IndexError, ValueError, TypeError, AttributeError, KeyError):
                row["start_soc"] = None
        
        # Trip start km (odometer at Manawar departure - from total_vehicle_distance field)
        try:
            manawar1_df_local = visit_slice(M1)
            odo_start = None
            if not manawar1_df_local.empty and 'odometer' in manawar1_df_local.columns:
                valid_odos = manawar1_df_local[manawar1_df_local['odometer'].notna()]['odometer']
                if not valid_odos.empty:
                    odo_start = valid_odos.iloc[-1]  # last valid reading before departure
            row["trip_start_km"] = float(odo_start) if odo_start is not None else None
        except Exception:
            row["trip_start_km"] = None
        
        charge_M_sec, charge_start_M, charge_end_M = charging_duration_sec(sub_charge_M)
        row["dhar_charging_duration"] = seconds_to_hhmm(charge_M_sec)
        
        if not sub_charge_M.empty and charge_start_M is not None:
            row["dhar_charging_start_date"] = charge_start_M.date()
            row["dhar_charging_start_time"] = charge_start_M.time()
            row["dhar_charging_end_time"] = charge_end_M.time()
            try:
                # Charging energy: SOC before charging -> max SOC after charging
                charge_start_soc = sub_charge_M.iloc[0]['soc'] if 'soc' in sub_charge_M.columns else 0
                charge_end_soc = sub_charge_M[['soc', 'soc_next']].max().max() if 'soc' in sub_charge_M.columns else charge_start_soc
            except (KeyError, TypeError, IndexError):
                charge_start_soc = 0
                charge_end_soc = 0
            if pd.notna(charge_start_soc) and pd.notna(charge_end_soc) and charge_end_soc >= charge_start_soc:
                row["dhar_kwh"] = (charge_end_soc - charge_start_soc) / 100.0 * BATTERY_CAPACITY_KWH
            # Closing SOC = SOC when charging ended (fully charged state)
            try:
                closing_soc = sub_charge_M[['soc', 'soc_next']].max().max() if 'soc' in sub_charge_M.columns else None
                row["closing_soc"] = float(closing_soc) if pd.notna(closing_soc) else None
            except (KeyError, TypeError, IndexError):
                row["closing_soc"] = None
        else:
            # No charging at Manawar: closing_soc = SOC when exiting Manawar geofence
            if not manawar1_df.empty:
                try:
                    last_row = manawar1_df.iloc[-1]
                    closing_soc_val = last_row['soc'].item() if 'soc' in last_row.index and pd.notna(last_row['soc']) else None
                    row["closing_soc"] = float(closing_soc_val) if closing_soc_val is not None else None
                except (IndexError, ValueError, TypeError, AttributeError, KeyError):
                    row["closing_soc"] = None
        
        if not manawar_loading_fence.empty:
            load_entry_ts = manawar_loading_fence.iloc[0]['start_ts']
            load_exit_ts = manawar_loading_fence.iloc[-1]['end_ts']
            load_sec = (load_exit_ts - load_entry_ts).total_seconds()
            row["manawar_loading_time"] = seconds_to_hhmm(load_sec)
        
        # ========== ROAD: MANAWAR -> JULWANIYA ==========
        road1 = pd.DataFrame()
        if M1["end_idx"] + 1 <= J["start_idx"] - 1:
            road1 = intervals_df.loc[M1["end_idx"] + 1:J["start_idx"] - 1].copy()
        
        julwaniya_in_ts = J["start_ts"]
        total_road1_sec = (julwaniya_in_ts - manawar_out_ts).total_seconds()
        
        if not road1.empty:
            is_road = ~road1["cluster"].isin(["Manawar", "Julwaniya", "Dhule"])
            road1_road = road1[is_road]
            road1_stoppage_sec = road1_road[road1_road["status"] == "Stop"]["duration_s"].sum()
            road1_moving_sec = road1_road[road1_road["status"] == "Moving"]["duration_s"].sum()
        else:
            road1_stoppage_sec = 0
            road1_moving_sec = 0
        
        row["manawar_julwaniya_stoppage"] = seconds_to_hhmm(road1_stoppage_sec)
        row["manawar_julwaniya_moving"] = seconds_to_hhmm(road1_moving_sec)
        row["manawar_julwaniya_total"] = seconds_to_hhmm(total_road1_sec)
        
        # ========== JULWANIYA BLOCK (J) - FORWARD JOURNEY ==========
        julwaniya_in_ts_actual = julwaniya_df.iloc[0]['start_ts'] if not julwaniya_df.empty else J["start_ts"]
        julwaniya_charging_fence = julwaniya_df[
            julwaniya_df["geofence"] == "Jhulwania Charging Point"
        ] if not julwaniya_df.empty else pd.DataFrame()
        # Use proper charging session detection instead of status=='Charging'
        sub_charge_J = julwaniya_df[
            (julwaniya_df["geofence"] == "Jhulwania Charging Point") &
            (julwaniya_df["is_charging"] == True)
        ] if (not julwaniya_df.empty and "is_charging" in julwaniya_df.columns) else pd.DataFrame()
        exit_timestamps = [julwaniya_df.iloc[-1]['end_ts']] if not julwaniya_df.empty else [J["end_ts"]]
        if not julwaniya_charging_fence.empty:
            exit_timestamps.append(julwaniya_charging_fence.iloc[-1]['end_ts'])
        if not sub_charge_J.empty:
            exit_timestamps.append(sub_charge_J.iloc[-1]['end_ts'])
        julwaniya_out_ts_actual = max(exit_timestamps)
        
        row["julwaniya_entry_time"] = julwaniya_in_ts_actual
        row["julwaniya_exit_time"] = julwaniya_out_ts_actual
        
        if not julwaniya_df.empty:
            try:
                # Odometer: first valid reading at Julwaniya entry
                odo_val = None
                if 'odometer' in julwaniya_df.columns:
                    valid_odos = julwaniya_df[julwaniya_df['odometer'].notna()]['odometer']
                    if not valid_odos.empty:
                        odo_val = valid_odos.iloc[0]
                row["closing_km_julwaniya"] = float(odo_val) if odo_val is not None else None
                # SOC at Julwaniya entry: first valid SOC reading
                soc_val = None
                if 'soc' in julwaniya_df.columns:
                    valid_socs = julwaniya_df[julwaniya_df['soc'].notna()]['soc']
                    if not valid_socs.empty:
                        soc_val = valid_socs.iloc[0]
                row["start_soc_julwaniya"] = float(soc_val) if soc_val is not None else None
                # end_soc_julwaniya: last valid SOC at Julwaniya exit
                end_soc_val = None
                if 'soc_next' in julwaniya_df.columns:
                    valid_end = julwaniya_df[julwaniya_df['soc_next'].notna()]['soc_next']
                    if not valid_end.empty:
                        end_soc_val = valid_end.iloc[-1]
                if end_soc_val is None and 'soc' in julwaniya_df.columns:
                    valid_end = julwaniya_df[julwaniya_df['soc'].notna()]['soc']
                    if not valid_end.empty:
                        end_soc_val = valid_end.iloc[-1]
                row["end_soc_julwaniya"] = float(end_soc_val) if end_soc_val is not None else None
            except (KeyError, TypeError, ValueError, AttributeError) as _e:
                logger.debug(f"julwaniya soc/odo error: {_e}")
                row["closing_km_julwaniya"] = None
                row["start_soc_julwaniya"] = None
                row["end_soc_julwaniya"] = None
        
        charge_J_sec, charge_start_ts, charge_end_ts = charging_duration_sec(sub_charge_J)
        row["julwaniya_charging_duration"] = seconds_to_hhmm(charge_J_sec)
        
        if not sub_charge_J.empty and charge_start_ts is not None:
            row["julwaniya_charging_start_date"] = charge_start_ts.date()
            row["julwaniya_charging_start_time"] = charge_start_ts.time()
            row["julwaniya_charging_end_time"] = charge_end_ts.time()
            
            try:
                charge_start_soc = sub_charge_J.iloc[0]['soc'] if 'soc' in sub_charge_J.columns else 0
                charge_end_soc = sub_charge_J[['soc', 'soc_next']].max().max() if 'soc' in sub_charge_J.columns else charge_start_soc
            except (KeyError, TypeError, IndexError):
                charge_start_soc = 0
                charge_end_soc = 0
            if pd.notna(charge_start_soc) and pd.notna(charge_end_soc) and charge_end_soc >= charge_start_soc:
                row["julwaniya_kwh"] = (charge_end_soc - charge_start_soc) / 100.0 * BATTERY_CAPACITY_KWH
            # Closing SOC = SOC when charging ended
            try:
                closing_soc = sub_charge_J[['soc', 'soc_next']].max().max() if 'soc' in sub_charge_J.columns else None
                row["closing_soc_julwaniya"] = float(closing_soc) if pd.notna(closing_soc) else None
            except (KeyError, TypeError, IndexError):
                row["closing_soc_julwaniya"] = None
        else:
            # No charging: closing_soc = SOC when exiting Julwaniya
            if not julwaniya_df.empty:
                try:
                    last_row = julwaniya_df.iloc[-1]
                    closing_soc_val = last_row['soc'].item() if 'soc' in last_row.index and pd.notna(last_row['soc']) else None
                    row["closing_soc_julwaniya"] = float(closing_soc_val) if closing_soc_val is not None else None
                except (IndexError, ValueError, TypeError, AttributeError, KeyError):
                    row["closing_soc_julwaniya"] = None
        
        julwaniya_tat_sec = (julwaniya_out_ts_actual - julwaniya_in_ts_actual).total_seconds()
        idle_J_sec = max(julwaniya_tat_sec - charge_J_sec, 0)
        row["idle_time_julwaniya"] = seconds_to_hhmm(idle_J_sec)
        
        # ========== ROAD: JULWANIYA -> DHULE ==========
        road2 = pd.DataFrame()
        if J["end_idx"] + 1 <= D["start_idx"] - 1:
            road2 = intervals_df.loc[J["end_idx"] + 1:D["start_idx"] - 1].copy()
        
        dhule_in_ts = D["start_ts"]
        total_road2_sec = (dhule_in_ts - julwaniya_out_ts_actual).total_seconds()
        
        if not road2.empty:
            is_road2 = ~road2["cluster"].isin(["Manawar", "Julwaniya", "Dhule"])
            road2_road = road2[is_road2]
            road2_stoppage_sec = road2_road[road2_road["status"] == "Stop"]["duration_s"].sum()
        else:
            road2_stoppage_sec = 0
        
        row["julwaniya_dhule_stoppage"] = seconds_to_hhmm(road2_stoppage_sec)
        
        if not road2.empty:
            try:
                odo_val = None
                if 'odometer' in road2.columns:
                    valid_odos = road2[road2['odometer'].notna()]['odometer']
                    if not valid_odos.empty:
                        odo_val = valid_odos.iloc[0]
                row["start_km_after_julwaniya"] = float(odo_val) if odo_val is not None else None
            except (KeyError, TypeError, ValueError):
                row["start_km_after_julwaniya"] = None
        
        # ========== DHULE BLOCK (D) ==========
        dhule_unloading_fence = dhule_df[
            dhule_df["geofence"] == "Dhule unloading"
        ] if not dhule_df.empty else pd.DataFrame()
        dhule_charging_fence = dhule_df[
            (dhule_df["geofence"] == "Charging Fence Dhule")
        ] if not dhule_df.empty else pd.DataFrame()
        # Use proper charging session detection instead of status=='Charging'
        sub_charge_D = dhule_df[
            (dhule_df["geofence"] == "Charging Fence Dhule") &
            (dhule_df["is_charging"] == True)
        ] if (not dhule_df.empty and "is_charging" in dhule_df.columns) else pd.DataFrame()
        exit_timestamps = [D["end_ts"]]
        if not dhule_unloading_fence.empty:
            exit_timestamps.append(dhule_unloading_fence.iloc[-1]['end_ts'])
        if not dhule_charging_fence.empty:
            exit_timestamps.append(dhule_charging_fence.iloc[-1]['end_ts'])
        if not sub_charge_D.empty:
            exit_timestamps.append(sub_charge_D.iloc[-1]['end_ts'])
        dhule_out_ts = max(exit_timestamps)
        
        row["dhule_entry_time"] = dhule_in_ts
        row["dhule_exit_time"] = dhule_out_ts
        
        if not dhule_df.empty:
            try:
                # Odometer: first valid reading at Dhule entry
                odo_val = None
                if 'odometer' in dhule_df.columns:
                    valid_odos = dhule_df[dhule_df['odometer'].notna()]['odometer']
                    if not valid_odos.empty:
                        odo_val = valid_odos.iloc[0]
                row["closing_km_dhule"] = float(odo_val) if odo_val is not None else None
                # SOC at Dhule entry: first valid SOC reading
                soc_val = None
                if 'soc' in dhule_df.columns:
                    valid_socs = dhule_df[dhule_df['soc'].notna()]['soc']
                    if not valid_socs.empty:
                        soc_val = valid_socs.iloc[0]
                row["start_soc_dhule"] = float(soc_val) if soc_val is not None else None
                # end_soc_dhule: last valid SOC at Dhule exit
                end_soc_val = None
                if 'soc_next' in dhule_df.columns:
                    valid_end = dhule_df[dhule_df['soc_next'].notna()]['soc_next']
                    if not valid_end.empty:
                        end_soc_val = valid_end.iloc[-1]
                if end_soc_val is None and 'soc' in dhule_df.columns:
                    valid_end = dhule_df[dhule_df['soc'].notna()]['soc']
                    if not valid_end.empty:
                        end_soc_val = valid_end.iloc[-1]
                row["end_soc_dhule"] = float(end_soc_val) if end_soc_val is not None else None
            except (KeyError, TypeError, ValueError, AttributeError) as _e:
                logger.debug(f"dhule soc/odo error: {_e}")
                row["closing_km_dhule"] = None
                row["start_soc_dhule"] = None
                row["end_soc_dhule"] = None
        
        charge_D_sec, charge_start_D, charge_end_D = charging_duration_sec(sub_charge_D)
        row["dhule_charging_duration"] = seconds_to_hhmm(charge_D_sec)
        
        if not sub_charge_D.empty and charge_start_D is not None:
            row["dhule_charging_start_date"] = charge_start_D.date()
            row["dhule_charging_start_time"] = charge_start_D.time()
            row["dhule_charging_end_time"] = charge_end_D.time()
            
            try:
                charge_start_soc = sub_charge_D.iloc[0]['soc'] if 'soc' in sub_charge_D.columns else 0
                charge_end_soc = sub_charge_D[['soc', 'soc_next']].max().max() if 'soc' in sub_charge_D.columns else charge_start_soc
            except (KeyError, TypeError, IndexError):
                charge_start_soc = 0
                charge_end_soc = 0
            if pd.notna(charge_start_soc) and pd.notna(charge_end_soc) and charge_end_soc >= charge_start_soc:
                row["dhule_kwh"] = (charge_end_soc - charge_start_soc) / 100.0 * BATTERY_CAPACITY_KWH
            # Closing SOC = SOC when charging ended
            try:
                closing_soc = sub_charge_D[['soc', 'soc_next']].max().max() if 'soc' in sub_charge_D.columns else None
                row["closing_soc_dhule"] = float(closing_soc) if pd.notna(closing_soc) else None
            except (KeyError, TypeError, IndexError):
                row["closing_soc_dhule"] = None
        else:
            # No charging: closing_soc = SOC when exiting Dhule
            if not dhule_df.empty:
                try:
                    last_row = dhule_df.iloc[-1]
                    closing_soc_val = last_row['soc'].item() if 'soc' in last_row.index and pd.notna(last_row['soc']) else None
                    row["closing_soc_dhule"] = float(closing_soc_val) if closing_soc_val is not None else None
                except (IndexError, ValueError, TypeError, AttributeError, KeyError):
                    row["closing_soc_dhule"] = None
        
        dhule_tat_sec = (dhule_out_ts - dhule_in_ts).total_seconds()
        idle_D_sec = max(dhule_tat_sec - charge_D_sec, 0)
        row["idle_time_dhule"] = seconds_to_hhmm(idle_D_sec)
        
        # ========== RETURN JOURNEY (INCLUDING SHUTTLES) ==========
        # Collect all intervals from end of forward Dhule to start of return Manawar
        road3 = pd.DataFrame()
        if D["end_idx"] + 1 <= M2["start_idx"] - 1:
            road3 = intervals_df.loc[D["end_idx"] + 1:M2["start_idx"] - 1].copy()
        
        back_mnwr_ts = M2["start_ts"]
        row["dhar_reach_date"] = back_mnwr_ts.date()
        row["dhar_reach_time"] = back_mnwr_ts  # Use full datetime, not just time
        
        if not manawar2_df.empty:
            try:
                odo_val = None
                if 'odometer' in manawar2_df.columns:
                    valid_odos = manawar2_df[manawar2_df['odometer'].notna()]['odometer']
                    if not valid_odos.empty:
                        odo_val = valid_odos.iloc[0]
                row["trip_closed_km"] = float(odo_val) if odo_val is not None else None
            except (KeyError, TypeError, ValueError):
                row["trip_closed_km"] = None
        
        # Calculate total charging in return segment (including shuttles)
        return_charging_sec = 0
        if not road3.empty:
            return_charging = road3[road3["status"] == "Charging"]
            return_charging_sec = return_charging["duration_s"].sum()
        
        # ========== TOTAL CALCULATIONS ==========
        # Total trip time from vehicle out time to return arrival
        total_trip_sec = (back_mnwr_ts - manawar_out_ts).total_seconds()
        row["vehicle_total_trip_time"] = seconds_to_hhmm(total_trip_sec)
        
        # Total charging: forward + return (shuttles included in return)
        total_charging_sec = charge_M_sec + charge_J_sec + charge_D_sec + return_charging_sec
        row["all_station_total_charging_hours"] = seconds_to_hhmm(total_charging_sec)
        
        # Calculate distance and energy for entire trip
        try:
            trip_intervals = pd.concat([manawar1_df, road1, julwaniya_df, road2, dhule_df, road3, manawar2_df], 
                                     ignore_index=True)
        except Exception as e:
            logger.warning(f"Error concatenating trip intervals for {vehicle_no}: {e}")
            trip_intervals = pd.DataFrame()
        
        if not trip_intervals.empty:
            try:
                # Distance calculation with error handling
                def safe_distance_calc(r):
                    try:
                        if pd.notna(r.get('lat_next')) and pd.notna(r.get('lon_next')) and pd.notna(r.get('lat')) and pd.notna(r.get('lon')):
                            return haversine_m(r['lat'], r['lon'], r['lat_next'], r['lon_next'])
                        return 0.0
                    except (TypeError, ValueError, KeyError):
                        return 0.0
                
                trip_intervals['distance_m'] = trip_intervals.apply(safe_distance_calc, axis=1)
                total_distance_km = trip_intervals['distance_m'].sum() / 1000.0
                row["total_distance_km"] = round(total_distance_km, 3) if pd.notna(total_distance_km) else 0.0
                
                # Energy calculation: Sum SOC decreases during actual transit (moving/idle on roads only)
                # Only count valid SOC pairs (exclude NaN/None values which shouldn't count as discharge)
                # Focus on road segments between geofences
                try:
                    total_soc_decrease = 0.0
                    
                    # Sum SOC decreases only in ROAD segments (between geofences)
                    # These represent actual travel discharge, not idle/charging
                    for segment_df in [road1, road2, road3]:
                        if not segment_df.empty:
                            # Only process rows where BOTH soc and soc_next are valid (not NaN)
                            # AND filter out unrealistic discharge values (>10% per segment = data corruption)
                            valid_rows = segment_df[(segment_df['soc'].notna()) & 
                                                     (segment_df['soc_next'].notna()) &
                                                     (segment_df['soc'] > segment_df['soc_next']) &
                                                     ((segment_df['soc'] - segment_df['soc_next']) <= 10)]
                            
                            if not valid_rows.empty:
                                discharges = valid_rows['soc'] - valid_rows['soc_next']
                                total_soc_decrease += discharges.sum()
                    
                    # Convert SOC % to kWh
                    total_energy_kwh = (total_soc_decrease / 100.0) * BATTERY_CAPACITY_KWH
                    
                except (TypeError, ValueError, KeyError, AttributeError):
                    total_energy_kwh = 0.0
                
                row["total_kwh"] = round(total_energy_kwh, 3) if pd.notna(total_energy_kwh) and total_energy_kwh > 0 else 0.0
                
                # Efficiency calculation with division by zero protection
                if total_distance_km > 0 and pd.notna(total_energy_kwh) and total_energy_kwh > 0:
                    row["efficiency_kwh_per_km"] = round(total_energy_kwh / total_distance_km, 3)
                else:
                    row["efficiency_kwh_per_km"] = None
                    
            except Exception as e:
                logger.error(f"Error calculating distance/energy for {vehicle_no}: {e}")
                row["total_distance_km"] = 0.0
                row["total_kwh"] = 0.0
                row["efficiency_kwh_per_km"] = None
        
        # Total KM from odometer with null checks
        try:
            start_km = row.get("trip_start_km")
            end_km = row.get("trip_closed_km")
            if start_km is not None and end_km is not None and pd.notna(start_km) and pd.notna(end_km):
                row["total_trip_km"] = round(float(end_km) - float(start_km), 3)
            else:
                row["total_trip_km"] = None
        except (TypeError, ValueError) as e:
            logger.warning(f"Error calculating total trip km for {vehicle_no}: {e}")
            row["total_trip_km"] = None

        # ========== PER-TRIP PERFORMANCE METRICS ==========
        # These granular seconds-based fields power the TripPerformanceSummary aggregation.
        try:
            dhule_charging_fence_names = {"Charging Fence Dhule"}

            # --- Plant area: ALL Manawar cluster + ALL Dhule cluster intervals ---
            loading_rows = manawar1_df[manawar1_df["geofence"] == "Manawar Loading Area"] if not manawar1_df.empty else pd.DataFrame()
            unloading_rows = dhule_df[dhule_df["geofence"] == "Dhule unloading"] if not dhule_df.empty else pd.DataFrame()

            def _sum_status(df, status_val):
                if df.empty or "status" not in df.columns or "duration_s" not in df.columns:
                    return 0.0
                return float(df[df["status"] == status_val]["duration_s"].sum())

            # loading/unloading stop times remain scoped to specific sub-fences
            loading_stop_s = _sum_status(loading_rows, "Stop")
            unloading_stop_s = _sum_status(unloading_rows, "Stop")
            row["loading_stop_time_s"] = loading_stop_s
            row["unloading_stop_time_s"] = unloading_stop_s

            # plant_area covers full Manawar cluster + full Dhule cluster
            plant_frames = [f for f in [manawar1_df, dhule_df] if not f.empty]
            if plant_frames:
                plant_all = pd.concat(plant_frames, ignore_index=True)
                row["plant_area_time_s"] = float(plant_all["duration_s"].sum()) if "duration_s" in plant_all.columns else 0.0
                row["plant_area_stop_time_s"] = _sum_status(plant_all, "Stop")
                row["plant_area_move_time_s"] = _sum_status(plant_all, "Moving")
            else:
                row["plant_area_time_s"] = 0.0
                row["plant_area_stop_time_s"] = 0.0
                row["plant_area_move_time_s"] = 0.0

            # --- Charging area (all charging geofences across all stations) ---
            m_charge_area = manawar1_df[manawar1_df["geofence"] == "Manawar Charging Point"] if not manawar1_df.empty else pd.DataFrame()
            j_charge_area = julwaniya_df[julwaniya_df["geofence"] == "Jhulwania Charging Point"] if not julwaniya_df.empty else pd.DataFrame()
            d_charge_area = dhule_df[dhule_df["geofence"] == "Charging Fence Dhule"] if not dhule_df.empty else pd.DataFrame()

            charge_area_frames = [f for f in [m_charge_area, j_charge_area, d_charge_area] if not f.empty]
            if charge_area_frames:
                all_charge_area = pd.concat(charge_area_frames, ignore_index=True)
                row["charging_area_time_s"] = float(all_charge_area["duration_s"].sum()) if "duration_s" in all_charge_area.columns else 0.0
                # Stop/move while NOT actively charging
                if "is_charging" in all_charge_area.columns:
                    not_plugged = all_charge_area[all_charge_area["is_charging"] != True]
                else:
                    not_plugged = all_charge_area
                row["charging_area_stop_time_s"] = _sum_status(not_plugged, "Stop")
                row["charging_area_move_time_s"] = _sum_status(not_plugged, "Moving")
            else:
                row["charging_area_time_s"] = 0.0
                row["charging_area_stop_time_s"] = 0.0
                row["charging_area_move_time_s"] = 0.0

            # Plugged time = sum of actual is_charging=True durations across all stations
            row["plugged_time_s"] = float(charge_M_sec + charge_J_sec + charge_D_sec)

            # --- Unplanned stoppages on road segments (outside all geofences) ---
            road_stop_s = 0.0
            for seg in [road1, road2, road3]:
                if not seg.empty and "status" in seg.columns and "cluster" in seg.columns and "duration_s" in seg.columns:
                    outside = seg[seg["cluster"].isna() | ~seg["cluster"].isin(["Manawar", "Julwaniya", "Dhule"])]
                    road_stop_s += float(outside[outside["status"] == "Stop"]["duration_s"].sum())
            row["unplanned_stoppage_time_s"] = road_stop_s

            # --- Gained SOC (sum of SOC charged at each station) ---
            def _soc_gain(start, end, has_charging):
                if not has_charging:
                    return 0.0
                try:
                    if start is not None and end is not None and pd.notna(start) and pd.notna(end) and float(end) > float(start):
                        return float(end) - float(start)
                except (TypeError, ValueError):
                    pass
                return 0.0

            m_gain = _soc_gain(row.get("start_soc"), row.get("closing_soc"), not sub_charge_M.empty)
            j_gain = _soc_gain(row.get("start_soc_julwaniya"), row.get("closing_soc_julwaniya"), not sub_charge_J.empty)
            d_gain = _soc_gain(row.get("start_soc_dhule"), row.get("closing_soc_dhule"), not sub_charge_D.empty)
            row["gained_soc"] = round(m_gain + j_gain + d_gain, 2)

            # --- Trip duration in seconds (mirrors vehicle_total_trip_time as numeric) ---
            row["trip_duration_s"] = float(total_trip_sec) if pd.notna(total_trip_sec) else None

        except Exception as _perf_err:
            logger.warning(f"Error computing performance metrics for {vehicle_no}: {_perf_err}")
            for _f in ["plant_area_time_s", "plant_area_stop_time_s", "plant_area_move_time_s",
                       "loading_stop_time_s", "unloading_stop_time_s", "charging_area_time_s",
                       "plugged_time_s", "charging_area_stop_time_s", "charging_area_move_time_s",
                       "unplanned_stoppage_time_s", "gained_soc", "trip_duration_s"]:
                if _f not in row:
                    row[_f] = None

        # Deviation metrics are intentionally excluded from TripCalculator to
        # keep MIS reporting isolated. Use the separate trip_deviation_service
        # for any deviation analysis outside MIS flows.
        
        # ========== PLANT-SPECIFIC LOADING/UNLOADING CALCULATIONS ==========
        # Calculate additional plant-level fields (not shown in exports)
        try:
            # Manawar Loading operations
            manawar_loading_area = manawar1_df[
                manawar1_df["geofence"] == "Manawar Loading Area"
            ] if not manawar1_df.empty else pd.DataFrame()
            
            if not manawar_loading_area.empty:
                load_entry_ts = manawar_loading_area.iloc[0]['start_ts']
                load_exit_ts = manawar_loading_area.iloc[-1]['end_ts']
                
                row["manawar_loading_entry_date"] = load_entry_ts.date()
                row["manawar_loading_entry_time"] = load_entry_ts.time()
                row["manawar_loading_exit_time"] = load_exit_ts.time()
                
                # Extra time after loading (from loading exit to vehicle departure)
                extra_time_sec = (manawar_out_ts - load_exit_ts).total_seconds()
                row["extra_time_after_loading"] = seconds_to_hhmm(max(extra_time_sec, 0))
            
            # Dhule Unloading operations
            dhule_unloading_area = dhule_df[
                dhule_df["geofence"] == "Dhule unloading"
            ] if not dhule_df.empty else pd.DataFrame()
            
            if not dhule_unloading_area.empty:
                unload_entry_ts = dhule_unloading_area.iloc[0]['start_ts']
                unload_exit_ts = dhule_unloading_area.iloc[-1]['end_ts']
                unload_duration_sec = (unload_exit_ts - unload_entry_ts).total_seconds()
                
                row["dhule_unload_date"] = unload_entry_ts.date()
                row["dhule_unload_entry_time"] = unload_entry_ts.time()
                row["dhule_unload_exit_date"] = unload_exit_ts.date()
                row["dhule_unload_exit_time"] = unload_exit_ts.time()
                row["dhule_unload_time"] = seconds_to_hhmm(unload_duration_sec)
                
                # Plant unload time (same as unload time for this implementation)
                row["dhule_plant_unload"] = seconds_to_hhmm(unload_duration_sec)
            
            # Journey time calculations
            # Stoppage D→J→M (return journey stoppage time)
            return_stoppage_sec = 0
            if not road3.empty:
                # Calculate stoppage time on return journey (excluding charge stations)
                return_road_stops = road3[
                    (road3["status"] == "Stop") & 
                    (~road3["cluster"].isin(["Manawar", "Julwaniya", "Dhule"])) &
                    (road3["cluster"].notna())
                ]
                if not return_road_stops.empty:
                    return_stoppage_sec = return_road_stops["duration_s"].sum()
            row["stoppage_d_j_m"] = seconds_to_hhmm(return_stoppage_sec)
            
            # Road time to Dhar (return journey moving time)
            return_moving_sec = 0
            if not road3.empty:
                # Calculate moving time on return journey
                return_road_moving = road3[
                    (road3["status"] == "Moving") & 
                    (~road3["cluster"].isin(["Manawar", "Julwaniya", "Dhule"])) &
                    (road3["cluster"].notna())
                ]
                if not return_road_moving.empty:
                    return_moving_sec = return_road_moving["duration_s"].sum()
            row["road_time_to_dhar"] = seconds_to_hhmm(return_moving_sec)
            
        except Exception as plant_err:
            logger.warning(f"Error computing plant-specific fields for {vehicle_no}: {plant_err}")
            # Set defaults for any missing fields
            for field in ["manawar_loading_entry_date", "manawar_loading_entry_time", 
                         "manawar_loading_exit_time", "extra_time_after_loading",
                         "dhule_unload_date", "dhule_unload_entry_time", "dhule_unload_exit_date",
                         "dhule_unload_exit_time", "dhule_unload_time", "dhule_plant_unload",
                         "stoppage_d_j_m", "road_time_to_dhar"]:
                if field not in row:
                    row[field] = None
        
        return row