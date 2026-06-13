import logging
from typing import Dict, Any

import pandas as pd

from .route_corridor import load_corridor
from .route_deviation import evaluate_segment_deviation

logger = logging.getLogger(__name__)


def _seconds_to_hhmm(sec: float) -> str:
    if pd.isna(sec) or sec is None:
        return "00:00"
    total_minutes = int(round(sec / 60.0))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def compute_route_deviation(intervals_df: pd.DataFrame, M1: Dict, J: Dict, D: Dict, M2: Dict) -> Dict[str, Any]:
    """
    Standalone route deviation computation for a single trip.

    This function intentionally lives outside TripCalculator to keep MIS isolated.
    Callers can pass the same visit dicts (M1, J, D, M2) used by TripCalculator
    along with its intervals_df to compute M→J, J→D, and D→M deviation metrics.

    Returns a dict with keys:
      - route_deviation_points_count
      - route_deviation_violations
      - route_deviation_duration
      - route_deviation_max_distance_m
      - route_deviation_segments (per-segment breakdown)
    """
    result = {
        "route_deviation_points_count": 0,
        "route_deviation_violations": 0,
        "route_deviation_duration": "00:00",
        "route_deviation_max_distance_m": 0.0,
        "route_deviation_segments": [],
    }

    try:
        # Build road-only slices between visits, mirroring TripCalculator logic
        road1 = pd.DataFrame()
        if M1["end_idx"] + 1 <= J["start_idx"] - 1:
            road1 = intervals_df.loc[M1["end_idx"] + 1:J["start_idx"] - 1].copy()
        road2 = pd.DataFrame()
        if J["end_idx"] + 1 <= D["start_idx"] - 1:
            road2 = intervals_df.loc[J["end_idx"] + 1:D["start_idx"] - 1].copy()
        road3 = pd.DataFrame()
        if D["end_idx"] + 1 <= M2["start_idx"] - 1:
            road3 = intervals_df.loc[D["end_idx"] + 1:M2["start_idx"] - 1].copy()

        road1_road = pd.DataFrame()
        if not road1.empty:
            road1_road = road1[~road1["cluster"].isin(["Manawar", "Julwaniya", "Dhule"])]
        road2_road = pd.DataFrame()
        if not road2.empty:
            road2_road = road2[~road2["cluster"].isin(["Manawar", "Julwaniya", "Dhule"])]
        road3_road = pd.DataFrame()
        if not road3.empty:
            road3_road = road3[~road3["cluster"].isin(["Manawar", "Julwaniya", "Dhule"])]

        cfg = load_corridor()
        dev_segments = []
        total_points = 0
        total_viol = 0
        total_dur = 0.0
        max_dev = 0.0

        # M -> J
        seg_MJ = cfg.get("M_J") if cfg else None
        if seg_MJ and seg_MJ.polyline:
            met = evaluate_segment_deviation(road1_road, seg_MJ.polyline, seg_MJ.buffer_m)
            dev_segments.append({"segment": "M_J", **met})
            total_points += met.get("points", 0)
            total_viol += met.get("violations", 0)
            total_dur += met.get("duration_s", 0.0)
            if met.get("points"):
                max_dev = max(max_dev, met.get("max_distance_m", 0.0))

        # J -> D
        seg_JD = cfg.get("J_D") if cfg else None
        if seg_JD and seg_JD.polyline:
            met = evaluate_segment_deviation(road2_road, seg_JD.polyline, seg_JD.buffer_m)
            dev_segments.append({"segment": "J_D", **met})
            total_points += met.get("points", 0)
            total_viol += met.get("violations", 0)
            total_dur += met.get("duration_s", 0.0)
            if met.get("points"):
                max_dev = max(max_dev, met.get("max_distance_m", 0.0))

        # D -> M (return)
        seg_DM = cfg.get("D_M") if cfg else None
        if seg_DM and seg_DM.polyline:
            met = evaluate_segment_deviation(road3_road, seg_DM.polyline, seg_DM.buffer_m)
            dev_segments.append({"segment": "D_M", **met})
            total_points += met.get("points", 0)
            total_viol += met.get("violations", 0)
            total_dur += met.get("duration_s", 0.0)
            if met.get("points"):
                max_dev = max(max_dev, met.get("max_distance_m", 0.0))

        result["route_deviation_points_count"] = total_points
        result["route_deviation_violations"] = total_viol
        result["route_deviation_duration"] = _seconds_to_hhmm(total_dur)
        result["route_deviation_max_distance_m"] = round(max_dev, 1)
        result["route_deviation_segments"] = dev_segments
    except Exception as e:
        logger.exception("route deviation computation failed: %s", e)

    return result
