"""
SOC (State of Charge) Analytics Module
Contains all battery/SOC related calculations and analytics.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional


# Constants for SOC calculations
EPSILON_SOC_STEP = 0.5  # Minimum SOC drop to consider as discharge (0.5%)
MAX_REALISTIC_DISCHARGE_STEP = 2  # Maximum realistic discharge in one step (2%), filter larger drops as errors


def compute_soc_discharge_from_series(
    s: pd.Series, epsilon: float = EPSILON_SOC_STEP
) -> float:
    """
    Compute the total State of Charge (SOC) discharge from a pandas Series
    of SOC values. It sums up all downward changes in SOC that are greater
     than a specified epsilon.

    Args:
        s: A pandas Series containing SOC values in ANY order
        epsilon: The minimum percentage drop in SOC to consider as discharge
                 in a single step. Smaller drops are ignored to filter noise.
                 Defaults to EPSILON_SOC_STEP (0.5%).

    Returns:
        The total SOC discharge in percentage points as a float. Returns np.nan
        if the input Series is empty or has only one data point after dropping NaNs.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Drop NaN values and reset index to ensure contiguous access for iteration.
    s = s.dropna().astype(float).reset_index(drop=True)
    # If there are 1 or fewer valid SOC points, discharge cannot be calculated.
    if len(s) <= 1:
        return np.nan
    
    logger.debug(f"🔋 SOC discharge calculation: {len(s)} valid points")
    logger.debug(f"   First value: {s.iloc[0]:.1f}%, Last value: {s.iloc[-1]:.1f}%")
    
    # Calculate the difference between consecutive SOC values (i - i+1).
    # This works regardless of data order: if sorted chronologically oldest→newest,
    # we get discharge drops. If newest→oldest, we get charge gains that we filter.
    drops = [s.iloc[i] - s.iloc[i + 1] for i in range(len(s) - 1)]
    
    # Count all drops for logging
    discharge_drops = [d for d in drops if epsilon < d <= MAX_REALISTIC_DISCHARGE_STEP]
    charge_gains = [d for d in drops if -MAX_REALISTIC_DISCHARGE_STEP <= d < -epsilon]
    
    logger.debug(f"   All transitions: {len(drops)}, Discharge: {len(discharge_drops)}, Charge: {len(charge_gains)}")
    
    # If we got mostly negative differences (charge gains), data is reversed
    # In that case, use negative drops instead
    if len(charge_gains) > len(discharge_drops):
        logger.debug(f"   Data appears to be in reversed order, using charge gains as discharge")
        discharge_drops = [abs(d) for d in charge_gains]
    
    # Sum discharge drops
    total_drop = sum(discharge_drops)
    
    logger.debug(f"   Total discharge: {total_drop:.2f}%")
    
    return float(total_drop)


def calculate_soc_analytics(vehicle_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate comprehensive SOC (State of Charge) analytics from vehicle data.

    Args:
        vehicle_data: List of vehicle data points with SOC information
                     (can be in any order - will be sorted by timestamp)

    Returns:
        Dictionary containing detailed SOC analytics
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not vehicle_data:
        return {
            "current_soc": 0,
            "starting_soc": 0,
            "start_soc": 0,
            "end_soc": 0,
            "soc_change": 0,
            "soc_change_type": "No Data",
            "avg_soc": 0,
            "min_soc": 0,
            "max_soc": 0,
            "total_discharge": 0,
            "discharge_events": 0,
            "charge_events": 0,
            "soc_stability": "Unknown",
        }

    # Sort by timestamp to ensure chronological order (oldest→newest)
    def get_timestamp(point):
        ts = point.get('gps_time') or point.get('last_connected') or point.get('timestamp') or ''
        return str(ts)
    
    sorted_data = sorted(vehicle_data, key=get_timestamp)
    
    # Extract SOC values in CHRONOLOGICAL ORDER
    soc_values = []
    for point in sorted_data:
        soc = point.get("soc")
        if soc is not None and isinstance(soc, (int, float)) and soc >= 0:
            soc_values.append(soc)

    if not soc_values:
        return {
            "current_soc": 0,
            "starting_soc": 0,
            "start_soc": 0,
            "end_soc": 0,
            "soc_change": 0,
            "soc_change_type": "No Data",
            "avg_soc": 0,
            "min_soc": 0,
            "max_soc": 0,
            "total_discharge": 0,
            "discharge_events": 0,
            "charge_events": 0,
            "soc_stability": "No Valid Data",
        }

    # Convert to pandas Series for advanced calculations (already in chronological order)
    soc_series = pd.Series(soc_values)

    # Basic SOC metrics - now in CHRONOLOGICAL order
    # Find first and last VALID (non-null) SOC values
    start_soc = None
    end_soc = None
    
    # Start SOC = first valid value in chronological order (oldest valid point)
    for point in sorted_data:  # Iterate from oldest to newest
        soc = point.get("soc")
        if soc is not None and isinstance(soc, (int, float)) and soc >= 0:
            start_soc = soc
            break
    
    # End SOC = last valid value in chronological order (newest valid point)
    for point in reversed(sorted_data):  # Iterate from newest to oldest
        soc = point.get("soc")
        if soc is not None and isinstance(soc, (int, float)) and soc >= 0:
            end_soc = soc
            break
    
    # Fallback if no valid SOC found
    if start_soc is None:
        start_soc = 0
    if end_soc is None:
        end_soc = 0
    
    current_soc = end_soc  # Current SOC is the most recent valid value
    starting_soc = start_soc  # Starting SOC is the oldest valid value

    # Calculate change from START to END
    soc_change = end_soc - start_soc

    # Determine change type
    if soc_change > 1:  # More than 1% increase
        change_type = "Charged"
    elif soc_change < -1:  # More than 1% decrease
        change_type = "Discharged"
    else:
        change_type = "Stable"

    # Statistical metrics
    avg_soc = soc_series.mean()
    min_soc = soc_series.min()
    max_soc = soc_series.max()

    # Advanced discharge calculation using the specialized function
    # soc_series is already in chronological order (oldest to newest)
    total_discharge = compute_soc_discharge_from_series(soc_series)
    if pd.isna(total_discharge):
        total_discharge = 0

    # Count discharge and charge events (filtering out unrealistic jumps)
    discharge_events = 0
    charge_events = 0

    for i in range(1, len(soc_values)):
        diff = soc_values[i - 1] - soc_values[i]  # Previous - Current
        # Only count if within realistic range (not sensor errors/reboots)
        if EPSILON_SOC_STEP < diff <= MAX_REALISTIC_DISCHARGE_STEP:  # Discharge event
            discharge_events += 1
        elif -MAX_REALISTIC_DISCHARGE_STEP <= diff < -EPSILON_SOC_STEP:  # Charge event
            charge_events += 1

    # Determine SOC stability
    soc_range = max_soc - min_soc
    if soc_range <= 5:
        stability = "Very Stable"
    elif soc_range <= 15:
        stability = "Stable"
    elif soc_range <= 30:
        stability = "Moderate"
    else:
        stability = "Variable"

    return {
        "current_soc": current_soc,
        "starting_soc": starting_soc,
        "start_soc": start_soc,  # Trip START SOC
        "end_soc": end_soc,  # Trip END SOC
        "soc_change": abs(soc_change),
        "soc_change_type": change_type,
        "avg_soc": round(avg_soc, 1),
        "min_soc": min_soc,
        "max_soc": max_soc,
        "total_discharge": round(total_discharge, 2),
        "discharge_events": discharge_events,
        "charge_events": charge_events,
        "soc_stability": stability,
        "soc_range": round(soc_range, 1) if "soc_range" in locals() else 0,
    }


def get_soc_insights(soc_analytics: Dict[str, Any]) -> List[str]:
    """
    Generate human-readable insights from SOC analytics.

    Args:
        soc_analytics: SOC analytics dictionary from calculate_soc_analytics()

    Returns:
        List of insight strings
    """
    insights = []

    # Battery level insights
    current_soc = soc_analytics.get("current_soc", 0)
    if current_soc < 20:
        insights.append("⚠️ Low battery - needs charging soon")
    elif current_soc < 50:
        insights.append("🔋 Moderate battery level")
    else:
        insights.append("✅ Good battery level")

    # Discharge insights
    total_discharge = soc_analytics.get("total_discharge", 0)
    if total_discharge > 20:
        insights.append(
            f"🔋 High energy consumption: {total_discharge:.1f}% discharged"
        )
    elif total_discharge > 10:
        insights.append(f"⚡ Moderate energy use: {total_discharge:.1f}% discharged")
    elif total_discharge > 0:
        insights.append(f"💚 Light energy use: {total_discharge:.1f}% discharged")

    # Charging insights
    charge_events = soc_analytics.get("charge_events", 0)
    if charge_events > 0:
        insights.append(f"🔌 {charge_events} charging session(s) detected")

    # Stability insights
    stability = soc_analytics.get("soc_stability", "Unknown")
    if stability == "Very Stable":
        insights.append("📊 Very consistent battery usage")
    elif stability == "Variable":
        insights.append("📈 Variable battery usage pattern")

    return insights


def format_soc_summary(soc_analytics: Dict[str, Any]) -> str:
    """
    Create a formatted summary string of SOC analytics.

    Args:
        soc_analytics: SOC analytics dictionary

    Returns:
        Formatted summary string
    """
    current = soc_analytics.get("current_soc", 0)
    change_type = soc_analytics.get("soc_change_type", "Unknown")
    total_discharge = soc_analytics.get("total_discharge", 0)

    if change_type == "Charged":
        return f"Battery at {current}% (+{soc_analytics.get('soc_change', 0)}% charged)"
    elif change_type == "Discharged":
        return f"Battery at {current}% (-{total_discharge:.1f}% used)"
    else:
        return f"Battery at {current}% (stable)"
