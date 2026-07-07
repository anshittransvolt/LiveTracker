"""
Energy Efficiency Calculator for LiveTracker

This module provides functions to calculate energy consumption and efficiency
metrics for vehicle trips based on distance traveled and SOC discharge.
"""

import pandas as pd
import numpy as np
from typing import Dict

# Default battery capacity in kWh (can be overridden)
BATTERY_KWH = 282.0


def compute_energy_and_eff(
    distance_km: float, soc_discharge: float, battery_kwh: float = BATTERY_KWH
) -> Dict[str, float]:
    """
    Compute energy consumed (kWh), energy efficiency (kWh/km), and
    SOC efficiency (km/%SOC) based on distance traveled and SOC discharge.

    Args:
        distance_km: The total distance traveled in kilometers.
        soc_discharge: The total SOC discharge in percentage points.
        battery_kwh: The total battery capacity in kWh. Defaults to BATTERY_KWH (280.0 kWh).

    Returns:
        A dictionary containing the computed values:
        'energy_kwh': Estimated energy consumption in kWh.
        'eff_kwh_per_km': Energy efficiency in kWh per kilometer (kWh/km) - industry standard. Returns NaN if distance is zero.
        'eff_km_per_soc': SOC efficiency in kilometers per %SOC discharge. Returns NaN if SOC discharge is zero.
        Returns a dictionary with energy_kwh even if distance/SOC are NaN.
    """
    # If SOC discharge is invalid, return NaN for all
    if pd.isna(soc_discharge) or soc_discharge <= 0:
        return {
            "energy_kwh": np.nan,
            "eff_kwh_per_km": np.nan,
            "eff_km_per_soc": np.nan,
        }

    # ✅ Always calculate energy consumption from SOC discharge
    # This is valid even without distance data
    energy = (soc_discharge / 100.0) * battery_kwh

    # Calculate efficiency in kWh/km (energy consumption per kilometer) - INDUSTRY STANDARD
    # Returns NaN if distance is zero or not provided
    eff_kwh = energy / distance_km if distance_km and distance_km > 0 else np.nan

    # Calculate efficiency in km/%SOC
    # This is valid if we have distance, even if distance is 0
    eff_soc = distance_km / soc_discharge if soc_discharge > 0 else np.nan

    return {"energy_kwh": energy, "eff_kwh_per_km": eff_kwh, "eff_km_per_soc": eff_soc}


def calculate_trip_efficiency(
    start_soc: float,
    end_soc: float,
    distance_km: float,
    battery_kwh: float = BATTERY_KWH,
) -> Dict[str, float]:
    """
    Helper function to calculate trip efficiency from start/end SOC and distance.

    Args:
        start_soc: Starting SOC percentage
        end_soc: Ending SOC percentage
        distance_km: Distance traveled in kilometers
        battery_kwh: Battery capacity in kWh

    Returns:
        Dictionary with efficiency metrics
    """
    soc_discharge = start_soc - end_soc
    return compute_energy_and_eff(distance_km, soc_discharge, battery_kwh)


def format_efficiency_stats(efficiency_data: Dict[str, float]) -> Dict[str, str]:
    """
    Format efficiency statistics for display in templates.

    Args:
        efficiency_data: Dictionary from compute_energy_and_eff

    Returns:
        Dictionary with formatted string values for display
    """
    formatted = {}

    for key, value in efficiency_data.items():
        if pd.isna(value) or np.isnan(value):
            formatted[key] = "N/A"
        elif key == "energy_kwh":
            formatted[key] = f"{value:.2f} kWh"
        elif key == "eff_kwh_per_km":
            formatted[key] = f"{value:.2f} kWh/km"
        elif key == "eff_km_per_soc":
            formatted[key] = f"{value:.2f} km/%SOC"
        else:
            formatted[key] = f"{value:.2f}"

    return formatted
