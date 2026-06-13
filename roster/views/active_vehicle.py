from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import date, datetime, timezone as dt_timezone
from django.conf import settings
from ..models import HorseTrolleyAssignment, TransportMaster
import logging
from livetracker.timebox import build_timebox_for_vehicle
from livetracker.views import fetch_timebox_data_from_fetch_geo

logger = logging.getLogger(__name__)


@login_required
def active_vehicles_report(request):
    """
    Display active vehicles report for a selected date.
    Data source: TWINS fetch_geo API (selected date only, UTC midnight → 23:59:59).
    """

    # ── Date selection ──────────────────────────────────────────────────────────
    selected_date_str = request.GET.get('date', '')
    if selected_date_str:
        try:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = date.today()
    else:
        selected_date = date.today()

    # Fetch only the selected date (UTC 00:00:00 → 23:59:59).
    start_dt = datetime(selected_date.year, selected_date.month, selected_date.day,
                        0, 0, 0, tzinfo=dt_timezone.utc)
    end_dt = datetime(selected_date.year, selected_date.month, selected_date.day,
                      23, 59, 59, tzinfo=dt_timezone.utc)

    # ── Fetch data from TWINS fetch_geo ─────────────────────────────────────────
    logger.info(f"Active vehicles: fetching TWINS data {start_dt} → {end_dt}")
    vehicle_records = fetch_timebox_data_from_fetch_geo(
        start_time=start_dt,
        end_time=end_dt,
        batch_window_hours=2,
    )
    # vehicle_records: Dict[registration_number → List[normalized_point]]
    # Each point already has: latitude, longitude, vehicle_status, last_connected,
    #                         gps_location, speed, odometer, registration_number

    # ── Process each vehicle ────────────────────────────────────────────────────
    vehicles_dict = {}

    for vehicle_no, records in vehicle_records.items():
        if not records:
            continue
        try:
            # Latest record by last_connected timestamp
            latest_rec = max(
                records,
                key=lambda r: (r.get("last_connected") or ""),
                default=None,
            )
            if not latest_rec:
                continue

            # Parse last_connected to a timezone-aware datetime
            last_connected_dt = None
            lc_str = latest_rec.get("last_connected")
            if lc_str:
                try:
                    if isinstance(lc_str, datetime):
                        last_connected_dt = lc_str
                    elif 'T' in str(lc_str):
                        last_connected_dt = datetime.fromisoformat(
                            str(lc_str).replace('Z', '+00:00'))
                    else:
                        last_connected_dt = datetime.strptime(lc_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            # ── DB lookups ──────────────────────────────────────────────────────
            try:
                vehicle_obj = TransportMaster.objects.get(horse_number=vehicle_no)
            except TransportMaster.DoesNotExist:
                vehicle_obj = None

            latest_assignment = None
            try:
                latest_assignment = HorseTrolleyAssignment.objects.filter(
                    horse__horse_number=vehicle_no,
                    assigned_date__date=selected_date,
                ).select_related('driver', 'horse').order_by('-assigned_date').first()
            except Exception:
                pass

            # ── Timebox: direction ──────────────────────────────────────────────
            timebox_route = None
            try:
                timebox_data = build_timebox_for_vehicle(records)
                direction = timebox_data.get("direction")
                if direction == "dhar_to_dhule":
                    timebox_route = "DHAR_TO_DHULE"
                elif direction == "dhule_to_dhar":
                    timebox_route = "DHULE_TO_DHAR"
            except Exception:
                pass

            # ── Daily KM from odometer (max - min of non-zero values) ────────────
            daily_km = 0.0
            try:
                odo_values = [
                    float(r.get("odometer") or 0)
                    for r in records
                    if r.get("odometer") and float(r.get("odometer") or 0) > 0
                ]
                if len(odo_values) >= 2:
                    daily_km = round(max(odo_values) - min(odo_values), 1)
            except Exception as e:
                logger.debug(f"Odometer calculation failed for {vehicle_no}: {e}")

            # ── Route: assignment wins, timebox as fallback ─────────────────────
            assignment_route = (
                latest_assignment.route
                if latest_assignment and latest_assignment.route
                else None
            )
            route = assignment_route or timebox_route

            # ── Status: map TWINS values to display labels ──────────────────────
            raw_status = (latest_rec.get("vehicle_status") or "").lower()
            status_map = {
                "traveling": "Moving", "move": "Moving", "moving": "Moving",
                "charging": "Charging", "yard": "Idle", "idle": "Idle",
                "stop": "Stop", "offline": "Offline",
            }
            status = status_map.get(raw_status, latest_rec.get("vehicle_status") or "Unknown")

            vehicles_dict[vehicle_no] = {
                'vehicle_no': vehicle_no,
                'vehicle_obj': vehicle_obj,
                'last_connected': last_connected_dt,
                'last_connected_str': lc_str,
                'status': status,
                'gps_location': latest_rec.get("gps_location"),
                'latest_assignment': latest_assignment,
                'route': route,
                'daily_km': daily_km,
            }
        except Exception as e:
            logger.error(f"Error processing vehicle {vehicle_no}: {e}")
            continue

    # Sort by last_connected descending (most recent first)
    active_vehicles = sorted(
        vehicles_dict.values(),
        key=lambda x: x.get('last_connected') or datetime.min.replace(tzinfo=dt_timezone.utc),
        reverse=True,
    )

    context = {
        'vehicles': active_vehicles,
        'current_time': timezone.now(),
        'total_count': len(active_vehicles),
        'selected_date': selected_date,
    }

    return render(request, 'reports/active_vehicles.html', context)

    