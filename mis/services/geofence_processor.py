"""
Geofence Processor Service
===========================
Detects vehicle location within geofences and builds visit sequences.
"""

import math
import numpy as np
import pandas as pd
import logging
from typing import Optional, List, Dict, Any
from shapely.geometry import Point
from .geofence_config import (
    CIRCLE_GEOFENCES,
    POLYGON_GEOMS,
    MANAWAR_FENCES,
    JULWANIYA_FENCES,
    DHULE_FENCES,
    MAX_GAP_MINUTES
)
from livetracker.data_sources.session_detectors import detect_charging_sessions

logger = logging.getLogger(__name__)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate Haversine distance in meters between two lat/lon points.
    
    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates
        
    Returns:
        Distance in meters
    """
    if None in (lat1, lon1, lat2, lon2):
        return 0.0
    
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def assign_geofence(lat: float, lon: float) -> Optional[str]:
    """
    Assign geofence name based on lat/lon coordinates.
    
    Args:
        lat: Latitude
        lon: Longitude
        
    Returns:
        Geofence name or None if outside all geofences
    """
    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
        return None
    
    pt = Point(lon, lat)
    
    # Check polygon geofences first
    for name, poly in POLYGON_GEOMS:
        try:
            if poly.contains(pt):
                return name
        except Exception as e:
            logger.warning(f"Error checking polygon {name}: {e}")
            continue
    
    # Check circle geofences
    for name, clat, clon, radius in CIRCLE_GEOFENCES:
        try:
            d = haversine_m(lat, lon, clat, clon)
            if d <= radius:
                return name
        except Exception as e:
            logger.warning(f"Error checking circle {name}: {e}")
            continue
    
    return None


def classify_cluster(geofence_name: Optional[str]) -> Optional[str]:
    """
    Classify geofence into cluster (Manawar, Julwaniya, Dhule).
    
    Args:
        geofence_name: Name of geofence
        
    Returns:
        Cluster name or None
    """
    if geofence_name is None:
        return None
    
    if geofence_name in MANAWAR_FENCES:
        return "Manawar"
    if geofence_name in JULWANIYA_FENCES:
        return "Julwaniya"
    if geofence_name in DHULE_FENCES:
        return "Dhule"
    
    return None


class GeofenceProcessor:
    """Process telemetry data to identify geofence visits."""
    
    def process_telemetry(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add geofence and cluster information to telemetry data.
        
        Args:
            df: Telemetry DataFrame with lat/lon columns
            
        Returns:
            DataFrame with added 'geofence' and 'cluster' columns
        """
        if df.empty:
            return df
        
        logger.info(f"Processing geofences for {len(df)} telemetry points")
        
        # Ensure we operate on a copy to avoid pandas SettingWithCopyWarning
        # when upstream code passes a slice/view of a DataFrame
        df = df.copy()
        
        # DATA CLEANING: Fill NaN SOC values with previous non-null value (forward fill)
        # This prevents NaN from being treated as 0 in calculations
        # SOC should not jump to 0 - if missing, use last known value
        if 'soc' in df.columns:
            # Sort by time to ensure forward fill is chronological
            df = df.sort_values('last_connected').reset_index(drop=True)
            # Forward fill NaN values per vehicle (don't fill across different vehicles)
            if 'vehicle_no' in df.columns:
                df['soc'] = df.groupby('vehicle_no')['soc'].ffill()
            else:
                df['soc'] = df['soc'].ffill()
            # Also fill any remaining leading NaN with 0 (vehicle starting)
            df['soc'] = df['soc'].fillna(0)
        
        # HIGHLY OPTIMIZED: Vectorized geofence assignment
        import numpy as np
        from functools import reduce
        
        # Initialize with None
        df['geofence'] = None
        df['cluster'] = None
        
        lats = df['lat'].values
        lons = df['lon'].values
        valid_mask = pd.notna(lats) & pd.notna(lons)
        
        if not valid_mask.any():
            logger.warning("No valid GPS coordinates found")
            return df
        
        # Check polygon geofences first (these take priority)
        for name, poly in POLYGON_GEOMS:
            # Vectorized point-in-polygon check
            points_to_check = valid_mask & df['geofence'].isna()
            if points_to_check.any():
                for idx in df[points_to_check].index:
                    lat, lon = df.loc[idx, 'lat'], df.loc[idx, 'lon']
                    if pd.notna(lat) and pd.notna(lon):
                        pt = Point(lon, lat)
                        try:
                            if poly.contains(pt):
                                df.loc[idx, 'geofence'] = name
                        except Exception:
                            continue
        
        # Check circle geofences for remaining points
        points_remaining = valid_mask & df['geofence'].isna()
        if points_remaining.any():
            remaining_lats = lats[points_remaining]
            remaining_lons = lons[points_remaining]
            remaining_indices = df[points_remaining].index
            
            for name, clat, clon, radius in CIRCLE_GEOFENCES:
                # Vectorized haversine distance calculation
                R = 6371000.0
                lat1_rad = np.radians(remaining_lats)
                lat2_rad = np.radians(clat)
                dlat = np.radians(clat - remaining_lats)
                dlon = np.radians(clon - remaining_lons)
                
                a = (np.sin(dlat / 2) ** 2 + 
                     np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2)
                c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
                distances = R * c
                
                # Assign geofence where distance <= radius and not yet assigned
                within_radius = distances <= radius
                for i, idx in enumerate(remaining_indices):
                    if within_radius[i] and pd.isna(df.loc[idx, 'geofence']):
                        df.loc[idx, 'geofence'] = name
        
        # Vectorized cluster classification
        df['cluster'] = df['geofence'].map(classify_cluster)
        
        geofence_count = df['geofence'].notna().sum()
        logger.info(f"Geofences assigned: {geofence_count}/{len(df)} points ({geofence_count/len(df)*100:.1f}%)")
        
        # Debug: Show detection breakdown by cluster
        cluster_counts = df['cluster'].value_counts(dropna=False)
        logger.info(f"Cluster detection breakdown: {dict(cluster_counts)}")
        
        # Debug: Show sample undetected points
        undetected = df[df['geofence'].isna()]
        if len(undetected) > 0:
            logger.info(f"Sample undetected GPS points: {len(undetected)} total")
            for _, row in undetected.head(3).iterrows():
                logger.info(f"  Undetected: {row['vehicle_no']} at ({row['lat']:.6f}, {row['lon']:.6f})")
        
        # Debug file writing disabled
        
        return df
    
    def build_intervals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Build time intervals between consecutive points per vehicle.
        
        Args:
            df: Telemetry DataFrame with geofence/cluster info
            
        Returns:
            DataFrame with intervals including next point data
        """
        if df.empty:
            return pd.DataFrame()
        
        logger.info("Building intervals between telemetry points")
        
        # OPTIMIZED: Vectorized interval building with shift
        # Sort by vehicle and time
        df = df.sort_values(['vehicle_no', 'last_connected']).reset_index(drop=True)
        
        # Shift to get next row values
        df['next_vehicle'] = df['vehicle_no'].shift(-1)
        df['end_ts'] = df['last_connected'].shift(-1)
        df['lat_next'] = df['lat'].shift(-1)
        df['lon_next'] = df['lon'].shift(-1)
        df['soc_next'] = df['soc'].shift(-1)
        df['odometer_next'] = df['end_odometer'].shift(-1)
        
        # Calculate duration
        df['duration_s'] = (df['end_ts'] - df['last_connected']).dt.total_seconds()
        
        # Filter: same vehicle, valid duration
        mask = (
            (df['vehicle_no'] == df['next_vehicle']) &
            (df['duration_s'] > 0) &
            (df['duration_s'] <= MAX_GAP_MINUTES * 60)
        )
        
        intervals_df = df[mask].rename(columns={
            'last_connected': 'start_ts',
            'vehicle_status': 'status',
            'end_odometer': 'odometer'
        })[['vehicle_no', 'start_ts', 'end_ts', 'duration_s', 'status', 
            'geofence', 'cluster', 'lat', 'lon', 'lat_next', 'lon_next',
            'soc', 'soc_next', 'odometer', 'odometer_next']].copy()
        
        logger.info(f"Built {len(intervals_df)} intervals")
        
        # Detect charging sessions per vehicle
        intervals_df = self._mark_charging_sessions(intervals_df)
        
        return intervals_df
    
    def _mark_charging_sessions(self, intervals_df: pd.DataFrame) -> pd.DataFrame:
        """
        Mark intervals where the vehicle is actively charging.

        An interval is classified as charging when SOC increases from the
        start of the interval to the start of the next interval (soc_next >
        soc).  The pre-computed soc_next column (built via shift in
        build_intervals) is used directly, which is far more reliable than
        passing aggregate intervals to detect_charging_sessions() whose 0.5 %
        per-point threshold is never met when telemetry arrives every ~60 s
        and EOC gain is only ~0.1 % per interval.

        Args:
            intervals_df: DataFrame with intervals (must have 'soc' and 'soc_next')

        Returns:
            DataFrame with 'is_charging' column added
        """
        if intervals_df.empty:
            intervals_df['is_charging'] = False
            return intervals_df

        has_soc = 'soc' in intervals_df.columns and 'soc_next' in intervals_df.columns
        if not has_soc:
            intervals_df['is_charging'] = False
            return intervals_df

        # Charging: SOC is increasing AND vehicle is not moving.
        # soc=0 readings are sensor resets/bad data (not real low SOC during charging)
        # and must be excluded to avoid pulling session start/end to noise points.
        soc_increasing = (
            intervals_df['soc'].notna() &
            intervals_df['soc_next'].notna() &
            (intervals_df['soc'] > 0) &
            (intervals_df['soc_next'] > intervals_df['soc'])
        )
        not_moving = True  # geofence filtering in trip_calculator handles location
        if 'status' in intervals_df.columns:
            not_moving = intervals_df['status'] != 'Moving'

        intervals_df['is_charging'] = soc_increasing & not_moving
        count = int(intervals_df['is_charging'].sum())
        logger.info(f"Marked {count} charging intervals out of {len(intervals_df)} total")
        return intervals_df
    
    def build_cluster_visits(self, intervals_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Merge flickering geofence entries into continuous cluster visits.
        
        Args:
            intervals_df: DataFrame with intervals for single vehicle
            
        Returns:
            List of visit dictionaries with cluster, start_idx, end_idx, start_ts, end_ts
        """
        visits = []
        current_cluster = None
        visit_start_idx = None
        last_cluster_idx = None
        
        for idx, row in intervals_df.iterrows():
            c = row['cluster']  # None / Manawar / Julwaniya / Dhule
            
            if c == current_cluster:
                if c is not None:
                    last_cluster_idx = idx
                continue
            
            # Cluster changed
            if current_cluster is not None:
                if c in {"Manawar", "Julwaniya", "Dhule"} and c != current_cluster:
                    if last_cluster_idx is not None:
                        visits.append({
                            "cluster": current_cluster,
                            "start_idx": visit_start_idx,
                            "end_idx": last_cluster_idx,
                            "start_ts": intervals_df.loc[visit_start_idx, 'start_ts'],
                            "end_ts": intervals_df.loc[last_cluster_idx, 'end_ts'],
                        })
                    current_cluster = None
                    visit_start_idx = None
                    last_cluster_idx = None
            
            # New cluster
            if c in {"Manawar", "Julwaniya", "Dhule"}:
                if current_cluster is None:
                    current_cluster = c
                    visit_start_idx = idx
                last_cluster_idx = idx
        
        # Close last open visit
        if current_cluster is not None and last_cluster_idx is not None:
            visits.append({
                "cluster": current_cluster,
                "start_idx": visit_start_idx,
                "end_idx": last_cluster_idx,
                "start_ts": intervals_df.loc[visit_start_idx, 'start_ts'],
                "end_ts": intervals_df.loc[last_cluster_idx, 'end_ts'],
            })
        
        return visits