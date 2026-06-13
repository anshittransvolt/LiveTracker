"""
Trip Performance Summary Service
=================================
Aggregates per-trip metrics from CalculatedTrip into monthly summaries
stored in TripPerformanceSummary.

Usage:
    from mis.services.trip_performance_summary_service import TripPerformanceSummaryService
    TripPerformanceSummaryService.build_for_month("2026-03")
    TripPerformanceSummaryService.build_for_month("2026-03", vehicle_no="MH15GB0001")
"""

import logging
from datetime import date
from typing import Optional

from django.db.models import Avg, Count, Q

logger = logging.getLogger(__name__)


def _seconds_to_hhmmss(sec) -> str:
    """Convert a numeric seconds value to HH:MM:SS string."""
    if sec is None:
        return "00:00:00"
    try:
        sec = int(round(float(sec)))
    except (TypeError, ValueError):
        return "00:00:00"
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


class TripPerformanceSummaryService:
    """Build and persist monthly trip performance summaries."""

    AVG_FIELDS = [
        "trip_duration_s",
        "plant_area_time_s",
        "plant_area_stop_time_s",
        "plant_area_move_time_s",
        "loading_stop_time_s",
        "unloading_stop_time_s",
        "charging_area_time_s",
        "plugged_time_s",
        "charging_area_stop_time_s",
        "charging_area_move_time_s",
        "unplanned_stoppage_time_s",
        "gained_soc",
        "efficiency_kwh_per_km",
    ]

    @classmethod
    def build_for_month(cls, month: str, vehicle_no: Optional[str] = None) -> int:
        """
        Compute and store performance summary for a given month.

        Args:
            month:      "YYYY-MM" string, e.g. "2026-03"
            vehicle_no: If provided, only recompute for this vehicle.

        Returns:
            Number of summary rows created/updated.
        """
        from ..models import CalculatedTrip, TripPerformanceSummary

        try:
            year, mon = int(month[:4]), int(month[5:7])
        except (ValueError, IndexError):
            raise ValueError(f"Invalid month format: {month!r}. Expected 'YYYY-MM'.")

        month_start = date(year, mon, 1)
        if mon == 12:
            month_end = date(year + 1, 1, 1)
        else:
            month_end = date(year, mon + 1, 1)

        qs = CalculatedTrip.objects.filter(
            log_date__gte=month_start,
            log_date__lt=month_end,
        )
        if vehicle_no:
            qs = qs.filter(vehicle_no=vehicle_no)

        # Group by vehicle
        vehicles = qs.values_list("vehicle_no", flat=True).distinct()
        saved = 0

        for veh in vehicles:
            vehicle_qs = qs.filter(vehicle_no=veh)
            agg = vehicle_qs.aggregate(
                trip_count=Count("id"),
                avg_trip_duration_s=Avg("trip_duration_s"),
                avg_plant_area_time_s=Avg("plant_area_time_s"),
                avg_plant_area_stop_time_s=Avg("plant_area_stop_time_s"),
                avg_plant_area_move_time_s=Avg("plant_area_move_time_s"),
                avg_loading_stop_time_s=Avg("loading_stop_time_s"),
                avg_unloading_stop_time_s=Avg("unloading_stop_time_s"),
                avg_charging_area_time_s=Avg("charging_area_time_s"),
                avg_plugged_time_s=Avg("plugged_time_s"),
                avg_charging_area_stop_time_s=Avg("charging_area_stop_time_s"),
                avg_charging_area_move_time_s=Avg("charging_area_move_time_s"),
                avg_unplanned_stoppage_time_s=Avg("unplanned_stoppage_time_s"),
                avg_gained_soc=Avg("gained_soc"),
                avg_efficiency_kwh_per_km=Avg("efficiency_kwh_per_km"),
            )

            defaults = {
                "trip_count": agg["trip_count"] or 0,
                "avg_trip_duration_s": agg["avg_trip_duration_s"],
                "avg_efficiency_kwh_per_km": agg["avg_efficiency_kwh_per_km"],
                "avg_plant_area_time_s": agg["avg_plant_area_time_s"],
                "avg_plant_area_stop_time_s": agg["avg_plant_area_stop_time_s"],
                "avg_plant_area_move_time_s": agg["avg_plant_area_move_time_s"],
                "avg_loading_stop_time_s": agg["avg_loading_stop_time_s"],
                "avg_unloading_stop_time_s": agg["avg_unloading_stop_time_s"],
                "avg_charging_area_time_s": agg["avg_charging_area_time_s"],
                "avg_plugged_time_s": agg["avg_plugged_time_s"],
                "avg_charging_area_stop_time_s": agg["avg_charging_area_stop_time_s"],
                "avg_charging_area_move_time_s": agg["avg_charging_area_move_time_s"],
                "avg_unplanned_stoppage_time_s": agg["avg_unplanned_stoppage_time_s"],
                "avg_gained_soc": agg["avg_gained_soc"],
            }

            TripPerformanceSummary.objects.update_or_create(
                month=month,
                vehicle_no=veh,
                defaults=defaults,
            )
            saved += 1
            logger.info(f"[PerfSummary] {month} {veh}: {agg['trip_count']} trips saved.")

        return saved

    @classmethod
    def build_for_date_range(cls, start_month: str, end_month: str,
                              vehicle_no: Optional[str] = None) -> int:
        """
        Build summaries for every month in [start_month, end_month] inclusive.

        Args:
            start_month: "YYYY-MM"
            end_month:   "YYYY-MM"

        Returns:
            Total rows created/updated.
        """
        from datetime import date

        def _parse(m):
            return (int(m[:4]), int(m[5:7]))

        sy, sm = _parse(start_month)
        ey, em = _parse(end_month)
        total = 0

        cy, cm = sy, sm
        while (cy, cm) <= (ey, em):
            month_str = f"{cy:04d}-{cm:02d}"
            total += cls.build_for_month(month_str, vehicle_no=vehicle_no)
            cm += 1
            if cm > 12:
                cm = 1
                cy += 1

        return total

    @classmethod
    def to_display_dict(cls, summary) -> dict:
        """
        Convert a TripPerformanceSummary instance to a human-readable dict
        with HH:MM:SS strings for duration fields and rounded decimals.
        """
        duration_fields = [
            ("avg_trip_duration_s", "Avg Duration/Trip"),
            ("avg_plant_area_time_s", "Avg Plant Area Time"),
            ("avg_plant_area_stop_time_s", "Avg Plant Area Stop Time"),
            ("avg_plant_area_move_time_s", "Avg Plant Area Move Time"),
            ("avg_loading_stop_time_s", "Avg Loading Stop Time"),
            ("avg_unloading_stop_time_s", "Avg Unloading Stop Time"),
            ("avg_charging_area_time_s", "Avg Charging Area Time"),
            ("avg_plugged_time_s", "Avg Plugged Time"),
            ("avg_charging_area_stop_time_s", "Avg Charging Area Stop Time"),
            ("avg_charging_area_move_time_s", "Avg Charging Area Move Time"),
            ("avg_unplanned_stoppage_time_s", "Avg Unplanned Stoppage Time"),
        ]
        result = {
            "Month": summary.month,
            "Vehicle number": summary.vehicle_no,
            "Trip Count": summary.trip_count,
            "Avg Efficiency (kWh/km)": (
                round(float(summary.avg_efficiency_kwh_per_km), 2)
                if summary.avg_efficiency_kwh_per_km is not None else None
            ),
            "Avg Gained SOC (%)": (
                round(float(summary.avg_gained_soc), 2)
                if summary.avg_gained_soc is not None else None
            ),
        }
        for field, label in duration_fields:
            result[label] = _seconds_to_hhmmss(getattr(summary, field, None))
        return result
