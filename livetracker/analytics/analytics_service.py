"""
Analytics service for processing vehicle telemetry data.
Contains business logic for calculating various analytics metrics.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import logging
import pandas as pd
import numpy as np
from .distance_utils import calculate_trip_analytics, parse_gps_location
from livetracker.data_sources import detect_charging_sessions, detect_stoppage_sessions
from .soc_analytics import (
    calculate_soc_analytics as calc_soc_analytics,
    get_soc_insights,
)
from .energy_efficiency import compute_energy_and_eff, format_efficiency_stats
# Import the proper calculation functions
from .distance_utils import compute_segment_distances, parse_gps_location
from .soc_analytics import compute_soc_discharge_from_series


def convert_to_json_serializable(obj):
    """
    Convert numpy/pandas types to native Python types for JSON serialization.
    """
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_to_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_json_serializable(item) for item in obj]
    elif pd.isna(obj):
        return None
    return obj


def get_current_status(vehicle_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get current status from the latest data point.

    Args:
        vehicle_data: List of vehicle data points sorted by time (newest first)

    Returns:
        Dictionary containing current status information
    """
    if not vehicle_data:
        return {
            "status": "No Data",
            "soc": 0,
            "last_update": None,
            "location": None,
            "driver_name": "Unknown",
        }

    # Get the latest (most recent) data point
    latest = vehicle_data[0]

    # Parse GPS location
    lat, lng = parse_gps_location(latest.get("gps_location", ""))

    # Format last update time
    last_connected = latest.get("last_connected")
    formatted_time = None
    if last_connected:
        try:
            # Parse ISO format datetime
            dt = datetime.fromisoformat(last_connected.replace("Z", "+00:00"))
            formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            formatted_time = last_connected

    return {
        "status": latest.get("vehicle_status", "Unknown"),
        "soc": latest.get("soc", 0),
        "last_update": formatted_time,
        "location": {"lat": lat, "lng": lng} if lat and lng else None,
        "driver_name": latest.get("driver_name", "Unknown"),
        "vehicle_id": latest.get("vehicle_id"),
        "vehicle_no": latest.get("vehicle_no"),
    }


def calculate_soc_analytics(vehicle_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate SOC analytics using the dedicated SOC analytics module.

    Args:
        vehicle_data: List of vehicle data dictionaries

    Returns:
        Dictionary with comprehensive SOC analytics
    """
    # Use the dedicated SOC analytics function
    soc_analytics = calc_soc_analytics(vehicle_data)

    # Add insights
    soc_analytics["insights"] = get_soc_insights(soc_analytics)

    return soc_analytics


def calculate_trip_analytics_enhanced(
    vehicle_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Calculate enhanced trip analytics using the distance calculation functions.

    Args:
        vehicle_data: List of vehicle data points (assumed to be in descending order - newest first)

    Returns:
        Dictionary containing trip analytics
    """

    # Use the existing calculate_trip_analytics function
    basic_analytics = calculate_trip_analytics(vehicle_data)

    # Add additional metrics
    if vehicle_data and len(vehicle_data) >= 2:
        # Calculate time span
        # Data comes in DESCENDING order (newest first), so:
        # vehicle_data[0] = newest (END of trip)
        # vehicle_data[-1] = oldest (START of trip)
        try:
           

            logger = logging.getLogger(__name__)

            start_time_str = vehicle_data[-1].get("last_connected", "")
            end_time_str = vehicle_data[0].get("last_connected", "")

            logger.info(
                f"Duration calculation: START={start_time_str}, END={end_time_str}"
            )

            start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
            end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))

            duration_seconds = (end_time - start_time).total_seconds()
            duration_minutes = int(duration_seconds / 60)

            logger.info(
                f"Duration: {duration_seconds} seconds = {duration_minutes} minutes"
            )

            # Duration should ALWAYS be positive (end > start)
            if duration_minutes < 0:
                logger.warning(
                    f"⚠️ Negative duration detected: {duration_minutes} min - taking absolute value"
                )
                duration_minutes = abs(duration_minutes)
        except Exception as e:
            

            logger = logging.getLogger(__name__)
            logger.error(f"Duration calculation error: {e}")
            duration_minutes = 0

        # Count different statuses
        status_counts = {}
        for point in vehicle_data:
            status = point.get("vehicle_status", "Unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        # Find most common status
        most_common_status = (
            max(status_counts, key=status_counts.get) if status_counts else "Unknown"
        )

        basic_analytics.update(
            {
                "duration_minutes": duration_minutes,
                "most_common_status": most_common_status,
                "status_distribution": status_counts,
            }
        )

    return basic_analytics


def calculate_event_summary(vehicle_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate time spent in different vehicle states (moving, stopped, charging).
    
    Args:
        vehicle_data: List of vehicle data points (in descending order - newest first)
    
    Returns:
        Dictionary containing time in seconds for each state
    """
    if len(vehicle_data) < 2:
        return {
            "moving": 0,
            "stopped": 0,
            "charging": 0,
            "total": 0,
        }
    
    try:
       
        logger = logging.getLogger(__name__)
        
        # Reverse to chronological order (oldest first) for proper time calculation
        chronological_data = list(reversed(vehicle_data))
        
        moving_time = 0
        stopped_time = 0
        charging_time = 0
        
        # Calculate time differences between consecutive points
        for i in range(len(chronological_data) - 1):
            current_point = chronological_data[i]
            next_point = chronological_data[i + 1]
            
            # Parse timestamps
            try:
                current_time_str = current_point.get("last_connected", "")
                next_time_str = next_point.get("last_connected", "")
                
                if not current_time_str or not next_time_str:
                    continue
                
                current_time = datetime.fromisoformat(current_time_str.replace("Z", "+00:00"))
                next_time = datetime.fromisoformat(next_time_str.replace("Z", "+00:00"))
                
                # Calculate time difference in seconds
                time_diff = (next_time - current_time).total_seconds()
                
                # Skip if time difference is negative or unreasonably large (>1 hour between points)
                if time_diff < 0 or time_diff > 3600:
                    continue
                
                # Get vehicle status for this segment
                status = current_point.get("vehicle_status", "Unknown").lower()
                
                # Categorize time based on status (case-insensitive check)
                # NOTE: Do not accumulate charging/stopped here; we'll derive them from session detectors below
                if "move" in status or "running" in status or "moving" in status:
                    moving_time += time_diff
                else:
                    # If status is unclear, do not assign to stopped; detectors will handle stoppage
                    pass
                    
            except Exception as e:
                logger.warning(f"Error calculating time segment: {e}")
                continue
        
        # Derive charging duration from session detectors (in minutes → seconds)
        try:
            charging_sessions = detect_charging_sessions(vehicle_data)
            print(f"🔌 DEBUG: detect_charging_sessions returned {len(charging_sessions)} sessions")
            for i, s in enumerate(charging_sessions):
                print(f"   Session {i}: {s}")
            charging_time = sum([(s.get('duration') or 0) * 60 for s in charging_sessions])
            print(f"🔌 DEBUG: Total charging_time = {charging_time}s")
            logger.info(f"🔌 Charging sessions found: {len(charging_sessions)}, total time: {charging_time}s")
        except Exception as e:
            logger.error(f"Error detecting charging sessions: {e}")
            charging_time = 0

        # Derive stoppage duration from session detectors (in minutes → seconds)
        try:
            stoppage_sessions = detect_stoppage_sessions(vehicle_data)
            print(f"⏹️  DEBUG: detect_stoppage_sessions returned {len(stoppage_sessions)} sessions")
            for i, s in enumerate(stoppage_sessions):
                print(f"   Session {i}: {s}")
            stopped_time = sum([(s.get('duration') or 0) * 60 for s in stoppage_sessions])
            print(f"⏹️  DEBUG: Total stopped_time = {stopped_time}s")
            logger.info(f"⏹️  Stoppage sessions found: {len(stoppage_sessions)}, total time: {stopped_time}s")
        except Exception as e:
            logger.error(f"Error detecting stoppage sessions: {e}")
            stopped_time = 0

        # Debug: Show sample vehicle status values
        try:
            sample_statuses = [str(p.get('vehicle_status', 'N/A')).lower() for p in vehicle_data[:10]]
            logger.info(f"📊 Sample vehicle statuses (first 10): {sample_statuses}")
        except Exception:
            pass

        total_time = moving_time + stopped_time + charging_time
        
        logger.info(f"Event summary calculated: Moving={moving_time}s, Stopped={stopped_time}s, Charging={charging_time}s")
        
        return {
            "moving": round(moving_time),
            "stopped": round(stopped_time),
            "charging": round(charging_time),
            "total": round(total_time),
        }
        
    except Exception as e:
      
        logger = logging.getLogger(__name__)
        logger.error(f"Error calculating event summary: {e}")
        return {
            "moving": 0,
            "stopped": 0,
            "charging": 0,
            "total": 0,
        }


def calculate_energy_efficiency_analytics(
    vehicle_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Calculate energy efficiency analytics for the vehicle trip using proper SOC discharge calculation.
    More lenient filtering: prioritizes SOC discharge calculation even if GPS data is sparse.

    Args:
        vehicle_data: List of vehicle data points (in descending order - newest first)

    Returns:
        Dictionary containing energy efficiency metrics
    """
    if len(vehicle_data) < 2:
        return {
            "energy_kwh": None,
            "eff_kwh_per_km": None,
            "eff_km_per_soc": None,
            "raw_data": {
                "energy_kwh": None,
                "eff_kwh_per_km": None,
                "eff_km_per_soc": None,
            },
            "status": "Insufficient data for efficiency calculation",
        }

    try:
        logger = logging.getLogger(__name__)
        
        # ========================================
        # STEP 1: Extract SOC values (most important for efficiency)
        # ========================================
        # NOTE: vehicle_data comes from API in descending order (newest first)
        # But compute_soc_discharge_from_series() needs chronological order (oldest first)
        # So we MUST reverse the data before extracting SOC values
        soc_values = []
        gps_points = []
        
        for point in reversed(vehicle_data):  # REVERSE to chronological order
            soc = point.get("soc")
            if soc and soc > 0:  # Only include valid positive SOC values
                soc_values.append(soc)
            
            # Separately collect GPS points for distance calculation
            lat, lng = parse_gps_location(point.get("gps_location", ""))
            if lat is not None and lng is not None and lat != 0 and lng != 0:
                gps_points.append({
                    "lat": lat,
                    "lng": lng,
                    "last_connected": point.get("last_connected"),
                })
        
        # Ensure we have valid SOC data
        if len(soc_values) < 2:
            logger.warning(f"⚠️ Insufficient valid SOC values: {len(soc_values)}")
            return {
                "energy_kwh": None,
                "eff_kwh_per_km": None,
                "eff_km_per_soc": None,
                "raw_data": {
                    "energy_kwh": None,
                    "eff_kwh_per_km": None,
                    "eff_km_per_soc": None,
                },
                "status": f"Insufficient valid SOC data ({len(soc_values)} points)",
            }
        
        # ========================================
        # STEP 2: Calculate SOC discharge (primary metric)
        # ========================================
        soc_series = pd.Series(soc_values)
        soc_discharge = compute_soc_discharge_from_series(soc_series)
        
        logger.info(f"SOC Analysis: {len(soc_values)} points, discharge={soc_discharge}%")
        
        # ========================================
        # STEP 3: Calculate distance from available GPS points
        # ========================================
        total_distance_km = 0
        if len(gps_points) >= 2:
            # Create dataframe from GPS points
            gps_df = pd.DataFrame(gps_points)
            # Reverse to chronological order (oldest first)
            gps_df = gps_df.iloc[::-1].reset_index(drop=True)
            # Calculate distances
            segment_distances = compute_segment_distances(gps_df, "lat", "lng")
            total_distance_km = segment_distances.sum()
            logger.info(f"Distance calculation: {len(gps_points)} GPS points, total={total_distance_km:.2f} km")
        else:
            logger.warning(f"⚠️ Insufficient GPS points for distance: {len(gps_points)}")
        
        # ========================================
        # STEP 4: Calculate efficiency metrics
        # ========================================
        from .energy_efficiency import compute_energy_and_eff
        
        # Get battery capacity (default 280 kWh)
        battery_kwh = 280.0
        
        # Calculate energy efficiency
        efficiency_data = compute_energy_and_eff(
            distance_km=total_distance_km if total_distance_km > 0 else 0,
            soc_discharge=soc_discharge,
            battery_kwh=battery_kwh
        )
        
        logger.info(f"Efficiency calculated: energy={efficiency_data.get('energy_kwh')}, eff_kwh/km={efficiency_data.get('eff_kwh_per_km')}")
        
        from .energy_efficiency import format_efficiency_stats
        formatted_data = format_efficiency_stats(efficiency_data)
        
        response = {
            **formatted_data,
            "raw_data": efficiency_data,
            "trip_distance_km": f"{total_distance_km:.2f} km" if total_distance_km > 0 else "No GPS data",
            "soc_discharge": f"{soc_discharge:.2f}%" if not pd.isna(soc_discharge) else "N/A",
            "soc_points_count": len(soc_values),
            "gps_points_count": len(gps_points),
            "status": "Success",
        }
        
        logger.info(f"Efficiency response: {response}")
        return response

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Error calculating efficiency: {str(e)}", exc_info=True)
        return {
            "energy_kwh": None,
            "eff_kwh_per_km": None,
            "eff_km_per_soc": None,
            "raw_data": {
                "energy_kwh": None,
                "eff_kwh_per_km": None,
                "eff_km_per_soc": None,
            },
            "status": f"Error: {str(e)}",
        }


def format_analytics_response(
    vehicle_data: List[Dict[str, Any]], registration_number: str
) -> Dict[str, Any]:
    """
    Create a comprehensive analytics response combining all metrics.

    Args:
        vehicle_data: Raw vehicle data from API (in descending order - newest first)
        registration_number: Vehicle registration number

    Returns:
        Formatted analytics response with JSON-serializable types
    """
    if not vehicle_data:
        return {
            "vehicle_no": registration_number,
            "data_points_count": 0,
            "message": f"Data is not available for this vehicle ({registration_number})",
            "current_status": {"status": "No Data"},
            "soc_analytics": {},
            "trip_analytics": {},
            "efficiency_analytics": {},
            "soc_time_series": [],
            "timestamp": datetime.now().isoformat(),
        }
    
    

    logger = logging.getLogger(__name__)

    # Log data order for debugging
    if vehicle_data and len(vehicle_data) >= 2:
        logger.info(f"Analytics for {registration_number}:")
        # logger.info(
        #     f"  First point (newest): time={vehicle_data[0].get('last_connected')}, soc={vehicle_data[0].get('soc')}"
        # )
        # logger.info(
            # f"  Last point (oldest): time={vehicle_data[-1].get('last_connected')}, soc={vehicle_data[-1].get('soc')}"
        # )

    current_status = get_current_status(vehicle_data)
    soc_analytics = calculate_soc_analytics(vehicle_data)
    trip_analytics = calculate_trip_analytics_enhanced(vehicle_data)
    efficiency_analytics = calculate_energy_efficiency_analytics(vehicle_data)
    event_summary = calculate_event_summary(vehicle_data)

    # logger.info(f"  Trip duration: {trip_analytics.get('duration_minutes')} min")
    # logger.info(f"  Total distance: {trip_analytics.get('total_distance')} km")
    # logger.info(
    #     f"  SOC: {soc_analytics.get('start_soc')}% → {soc_analytics.get('end_soc')}%"
    # )
    # logger.info(f"  Efficiency: {efficiency_analytics.get('eff_km_per_kwh')}")


    # Prepare SOC time series for graphing

    soc_time_series = []
    for point in vehicle_data:
        soc = point.get("soc")
        status = point.get("vehicle_status", "Unknown")
        timestamp = point.get("last_connected")
        # Only include points with valid SOC and timestamp
        if soc is not None and timestamp:
            soc_time_series.append({
                "soc": soc,
                "status": status,
                "timestamp": timestamp,
            })
    # If no valid points, add a warning entry
    if not soc_time_series:
        soc_time_series.append({
            "soc": 0,
            "status": "No Data",
            "timestamp": None,
        })

    # print("soc_time_series:", soc_time_series) #upto this data is there

    response = {
        "vehicle_no": registration_number,
        "data_points_count": len(vehicle_data),
        "current_status": current_status,
        "soc_analytics": soc_analytics,
        "trip_analytics": trip_analytics,
        "efficiency_analytics": efficiency_analytics,
        "event_summary": event_summary,
        "soc_time_series": soc_time_series,
        "timestamp": datetime.now().isoformat(),
    }

    # Convert all numpy/pandas types to native Python types
    return convert_to_json_serializable(response)
