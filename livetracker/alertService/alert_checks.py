"""Main alert check processor - handles all vehicle state checks and alert generation.

This module encapsulates all the business logic for:
- Geofence entry/exit detection with debouncing
- Dwell time checks (charging, loading, weighing, etc.)
- SOC and battery checks
- Transit time SLA validation
- Feed-gap detection
- Unplanned stop detection

The single entry point is `process_vehicle_record()` which takes a record and state,
performs all checks, updates state, and returns generated alerts.
"""

from typing import Tuple, Optional
from django.utils import timezone
from datetime import timedelta
from livetracker.models import VehicleState
from livetracker.alertService.alert_creation import create_alert_row
from livetracker.alertService.event_mapping import EventIDs
from livetracker.alertService.geofence import point_in_geofences
from livetracker.alertService.alert_constants import (
    DEBOUNCE_SECONDS,
    FEED_GAP_SECONDS,
    CHARGING_OVER_SECONDS,
    CHARGING_FULL_STUCK_SECONDS,
    TARE_DWELL_SECONDS,
    GROSS_DWELL_SECONDS,
    LOADING_DWELL_SECONDS,
    TARPULIN_DWELL_SECONDS,
    MAHA_BORDER_DWELL_SECONDS,
    UNLOADING_DWELL_SECONDS,
    UNPLANNED_STOP_SECONDS,
    MANAWAR_GEOFENCE_NAMES,
    MANAWAR_OUT,
    D1_JHULWANIA,
    D2_JHULWANIA,
    DHULE_GATE,
    MANAWAR_TO_JHULWANIA_MIN,
    MANAWAR_TO_JHULWANIA_MAX,
    MANAWAR_TO_JHULWANIA_TARGET,
    MANAWAR_TO_JHULWANIA_TOL,
    JHULWANIA_TO_DHULE_MIN,
    JHULWANIA_TO_DHULE_MAX,
    JHULWANIA_TO_DHULE_TARGET,
    JHULWANIA_TO_DHULE_TOL,
)
import dateutil.parser
from livetracker.services.route_corridor import load_corridor
from livetracker.services.route_deviation import point_to_polyline_distance_m


def parse_gps(gps_location: str) -> Tuple[Optional[float], Optional[float]]:
    """Parse GPS location string 'lat,lon' into floats."""
    try:
        parts = gps_location.split(",")
        lat = float(parts[0].strip())
        lon = float(parts[1].strip())
        return lat, lon
    except Exception:
        return None, None


def create_alert_with_throttling(state, event_id, now_ts, *args, **kwargs):
    """
    Wrapper for create_alert_row that applies throttling.
    Returns the alert if created, None if throttled.
    """
    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
    from livetracker.alertService.event_mapping import EventMapping
    
    # Get alert_type from event_id for throttling check
    alert_type = EventMapping.get_alert_type_from_event_id(event_id)
    
    # Check if alert should be throttled
    if should_throttle_alert(state, alert_type, now_ts):
        return None  # Throttled
    
    # Create the alert
    alert = create_alert_row(*args, event_id=event_id, **kwargs)
    
    # Update throttling timestamp
    update_alert_timestamp(state, alert_type, now_ts)
    
    return alert


def process_vehicle_record(
    state: VehicleState, record: dict, alerts_generated: list, throttled_counts: dict = None, spv: str = None
) -> None:
    """
    Process a single vehicle record and update state with all checks.
    Implements stateful deduplication: suppresses alerts if the same alert type and context were already sent and the situation hasn't changed.
    """
    if throttled_counts is None:
        throttled_counts = {}
    now = timezone.now()

    # Extract record fields
    vehicle_id = record.get("vehicle_id")
    vehicle_no = record.get("vehicle_no")
    driver_name = record.get("driver_name")
    gps_location = record.get("gps_location") or ""
    soc = record.get("soc")
    status = record.get("vehicle_status")
    last_connected_str = record.get("last_connected")

    try:
        last_connected = (
            dateutil.parser.isoparse(last_connected_str) if last_connected_str else None
        )
    except Exception:
        last_connected = None

    lat, lon = parse_gps(gps_location)

    # Update identifying fields
    state.vehicle_no = vehicle_no or state.vehicle_no
    state.driver_name = driver_name or state.driver_name
    if last_connected:
        state.last_connected = last_connected

    # Detect current geofence
    current_gf = None
    if lat is not None and lon is not None:
        current_gf = point_in_geofences(lat, lon)

    now_ts = timezone.now()

    # Track last alert type and context for deduplication
    if not hasattr(state, "_last_alerts"):  # {alert_type: (context_hash, timestamp)}
        state._last_alerts = {}

    def should_send_alert(alert_type, context):
        import hashlib

        context_str = str(context)
        context_hash = hashlib.md5(context_str.encode()).hexdigest()
        last = state._last_alerts.get(alert_type)
        if last and last[0] == context_hash:
            return False  # Suppress duplicate
        state._last_alerts[alert_type] = (context_hash, now_ts)
        return True

    # ===== GEOFENCE ENTRY/EXIT LOGIC WITH DEBOUNCING =====
    if current_gf and state.current_geofence != current_gf:
        # Entering a geofence candidate
        if state.inside_since is None:
            state.inside_since = now_ts
            state.outside_since = None
        else:
            elapsed = (now_ts - state.inside_since).total_seconds()
            if elapsed >= DEBOUNCE_SECONDS:
                # Stable entry confirmed
                prev_geofence = state.current_geofence
                state.current_geofence = current_gf
                state.outside_since = None
                state.stop_start_ts = None

                # Gate In event (Manawar)
                if (
                    current_gf in MANAWAR_GEOFENCE_NAMES
                    and prev_geofence not in MANAWAR_GEOFENCE_NAMES
                ):
                    text = f"[EVENT] {vehicle_no}  — Gate In (Manawar) at {current_gf}"
                    event_id = EventIDs.GATE_IN_MANAWAR
                    context = (vehicle_id, vehicle_no, current_gf)
                    from livetracker.alertService.event_mapping import EventMapping
                    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
                    alert_type = EventMapping.get_alert_type_from_event_id(event_id)
                    if should_send_alert(alert_type, context) and not should_throttle_alert(state, alert_type, now_ts):
                        a = create_alert_row(
                            vehicle_id,
                            vehicle_no,
                            driver_name,
                            gps_location,
                            current_gf,
                            lat,
                            lon,
                            soc,
                            event_id,
                            text,
                        spv=spv,
                        )
                        update_alert_timestamp(state, alert_type, now_ts)
                        alerts_generated.append(a)

                # Arrival alerts (Dabhashi, Dharampuri)
                if (
                    current_gf in ("Dabhashi", "Dharampuri")
                    and prev_geofence != current_gf
                ):
                    event_id = (
                        EventIDs.ARRIVAL_DABHASHI
                        if current_gf == "Dabhashi"
                        else EventIDs.ARRIVAL_DHARAMPURI
                    )
                    text = f"[EVENT] {vehicle_no}  — Arrived at {current_gf}"
                    context = (vehicle_id, vehicle_no, current_gf)
                    from livetracker.alertService.event_mapping import EventMapping
                    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
                    alert_type = EventMapping.get_alert_type_from_event_id(event_id)
                    if should_send_alert(alert_type, context) and not should_throttle_alert(state, alert_type, now_ts):
                        a = create_alert_row(
                            vehicle_id,
                            vehicle_no,
                            driver_name,
                            gps_location,
                            current_gf,
                            lat,
                            lon,
                            soc,
                            event_id,
                            text,
                        spv=spv,
                        )
                        update_alert_timestamp(state, alert_type, now_ts)
                        alerts_generated.append(a)
    else:
        if (state.inside_since is not None) and (current_gf != state.current_geofence):
            pass  # Keep inside_since for candidate tracking

    # Handle exit
    if state.current_geofence is not None and state.current_geofence != current_gf:
        if state.outside_since is None:
            state.outside_since = now_ts
        else:
            elapsed_out = (now_ts - state.outside_since).total_seconds()
            if elapsed_out >= DEBOUNCE_SECONDS:
                # Stable exit
                exited_gf = state.current_geofence
                state.current_geofence = None
                state.inside_since = None
                state.outside_since = None

                # Gate Out event
                if exited_gf == MANAWAR_OUT:
                    state.last_departure_ts = now_ts
                    state.last_departure_geofence = MANAWAR_OUT
                    text = f"[EVENT] {vehicle_no} — Gate Out (Manawar) at {exited_gf}"
                    event_id = EventIDs.GATE_OUT_MANAWAR
                    context = (vehicle_id, vehicle_no, exited_gf)
                    from livetracker.alertService.event_mapping import EventMapping
                    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
                    alert_type = EventMapping.get_alert_type_from_event_id(event_id)
                    if should_send_alert(alert_type, context) and not should_throttle_alert(state, alert_type, now_ts):
                        a = create_alert_row(
                            vehicle_id,
                            vehicle_no,
                            driver_name,
                            gps_location,
                            exited_gf,
                            lat,
                            lon,
                            soc,
                            event_id,
                            text,
                        spv=spv,
                        )
                        update_alert_timestamp(state, alert_type, now_ts)
                        alerts_generated.append(a)

    # ===== CHECKS WHEN INSIDE GEOFENCE =====
    if state.current_geofence:
        if state.inside_since is None:
            state.inside_since = now_ts
        inside_duration = (now_ts - state.inside_since).total_seconds()

        # Charging dwell check
        def charging_context():
            return (vehicle_id, vehicle_no, state.current_geofence, status)

        if should_send_alert("charging_dwell", charging_context()):
            _check_charging_dwell(
                state,
                now_ts,
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                lat,
                lon,
                soc,
                status,
                alerts_generated,
            spv=spv,
            )

        # SOC 100% stuck check
        def soc_context():
            return (vehicle_id, vehicle_no, state.current_geofence, soc)

        if should_send_alert("soc_100_stuck", soc_context()):
            _check_soc_100_stuck(
                state,
                now_ts,
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                lat,
                lon,
                soc,
                alerts_generated,
                throttled_counts,
            spv=spv,
            )

        # Dwell checks
        def dwell_context(area):
            return (vehicle_id, vehicle_no, area, inside_duration)

        if should_send_alert("weighing_dwell", dwell_context("Weighing Area")):
            _check_weighing_dwell(
                state,
                inside_duration,
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                lat,
                lon,
                soc,
                alerts_generated,
            spv=spv,
            )
        if should_send_alert("loading_dwell", dwell_context("Loading Area")):
            _check_loading_dwell(
                state,
                inside_duration,
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                lat,
                lon,
                soc,
                alerts_generated,
            spv=spv,
            )
        if should_send_alert("tarpaulin_dwell", dwell_context("Tarpulien")):
            _check_tarpaulin_dwell(
                state,
                inside_duration,
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                lat,
                lon,
                soc,
                alerts_generated,
            spv=spv,
            )
        if should_send_alert("maha_border_dwell", dwell_context("Maha Border")):
            _check_maha_border_dwell(
                state,
                inside_duration,
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                lat,
                lon,
                soc,
                alerts_generated,
            spv=spv,
            )
        if should_send_alert("unloading_dwell", dwell_context("Dhule Circle Geofence")):
            _check_unloading_dwell(
                state,
                inside_duration,
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                lat,
                lon,
                soc,
                alerts_generated,
            spv=spv,
            )

        # Transit checks
        def transit_context():
            return (
                vehicle_id,
                vehicle_no,
                state.current_geofence,
                state.last_departure_geofence,
            )

        if should_send_alert("transit_check", transit_context()):
            _check_transit(
                state,
                now_ts,
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                lat,
                lon,
                soc,
                alerts_generated,
            spv=spv,
            )

    # ===== CHECKS WHEN OUTSIDE GEOFENCE =====
    if not state.current_geofence:

        def stop_context():
            return (vehicle_id, vehicle_no, lat, lon, status)

        if should_send_alert("unplanned_stop", stop_context()):
            _check_unplanned_stop(
                state,
                now_ts,
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                lat,
                lon,
                soc,
                status,
                alerts_generated,
                throttled_counts,
            spv=spv,
            )

        # Route deviation check against nearest corridor segment when Moving
        from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
        if status == "Moving" and lat is not None and lon is not None:
            try:
                cfg = load_corridor()
                if cfg:
                    best_key = None
                    best_d = float("inf")
                    best_buf = 0.0
                    for key in ("M_J", "J_D", "D_M"):
                        seg = cfg.get(key)
                        if not seg or not seg.polyline:
                            continue
                        d = point_to_polyline_distance_m(float(lat), float(lon), seg.polyline)
                        if d < best_d:
                            best_key = key
                            best_d = d
                            best_buf = float(seg.buffer_m or 3000)
                    if best_key and best_d > best_buf:
                        if should_throttle_alert(state, 'route_deviation', now_ts):
                            throttled_counts['route_deviation'] = throttled_counts.get('route_deviation', 0) + 1
                        else:
                            text = f"{vehicle_no}  — Route deviation {int(best_d)}m outside corridor ({best_key.replace('_','→')}) at {lat:.5f},{lon:.5f}"
                            a = create_alert_row(
                                vehicle_id,
                                vehicle_no,
                                driver_name,
                                gps_location,
                                None,
                                lat,
                                lon,
                                soc,
                                EventIDs.ROUTE_DEVIATION,
                                text,
                            spv=spv,
                            )
                            alerts_generated.append(a)
                            update_alert_timestamp(state, 'route_deviation', now_ts)
            except Exception:
                # Keep alert pipeline resilient
                pass

    # ===== UPDATE STATE FIELDS =====
    state.last_lat = lat if lat is not None else state.last_lat
    state.last_lon = lon if lon is not None else state.last_lon
    state.last_soc = soc if soc is not None else state.last_soc

    # Handle status transitions
    if state.last_status != status:
        if status == "Charging":
            state.charging_start_ts = now_ts
        else:
            state.charging_start_ts = None

        if status != "Stop":
            state.stop_start_ts = None

    state.last_status = status


# ===== PRIVATE CHECK HELPER FUNCTIONS =====


def _check_charging_dwell(
    state,
    now_ts,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    status,
    alerts_generated,
    spv=None,
):
    """Check for charging overrun."""
    if state.current_geofence and status == "Charging":
        if state.charging_start_ts is None:
            state.charging_start_ts = now_ts
        else:
            duration = (now_ts - state.charging_start_ts).total_seconds()
            if duration >= CHARGING_OVER_SECONDS:
                text = f"{vehicle_no}  — Charging at {state.current_geofence} > 90 min (entered {state.inside_since.isoformat()})"
                a = create_alert_row(
                    vehicle_id,
                    vehicle_no,
                    driver_name,
                    gps_location,
                    state.current_geofence,
                    lat,
                    lon,
                    soc,
                    EventIDs.CHARGING_OVERRUN,
                    text,
                spv=spv,
                )
                alerts_generated.append(a)
    else:
        state.charging_start_ts = None


def _check_soc_100_stuck(
    state,
    now_ts,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
    throttled_counts,
    spv=None,
):
    """Check for SOC stuck at 100%."""
    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
    
    if soc == 100:
        if state.last_soc != 100:
            state.last_alert_ts = now_ts
        else:
            if state.last_alert_ts:
                if (
                    now_ts - state.last_alert_ts
                ).total_seconds() >= CHARGING_FULL_STUCK_SECONDS:
                    # Check if alert should be throttled
                    if should_throttle_alert(state, 'charging_full_stuck', now_ts):
                        throttled_counts['charging_full_stuck'] = throttled_counts.get('charging_full_stuck', 0) + 1
                        return  # Skip this alert due to throttling
                    
                    text = f"{vehicle_no}  — SOC=100% for >5 min at {state.current_geofence}"
                    a = create_alert_row(
                        vehicle_id,
                        vehicle_no,
                        driver_name,
                        gps_location,
                        state.current_geofence,
                        lat,
                        lon,
                        soc,
                        EventIDs.CHARGING_FULL_STUCK,
                        text,
                    spv=spv,
                    )
                    alerts_generated.append(a)
                    
                    # Update throttling timestamp
                    update_alert_timestamp(state, 'charging_full_stuck', now_ts)
    else:
        state.last_alert_ts = None


def _check_weighing_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
    spv=None,
):
    """Check for weighing area dwell overrun."""
    if state.current_geofence == "Weighing Area" and state.last_status == "Stop":
        if inside_duration >= TARE_DWELL_SECONDS:
            text = f"{vehicle_no}  — Tare weight dwell in Weighing Area > {TARE_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Weighing Area",
                lat,
                lon,
                soc,
                EventIDs.TARE_WEIGHT_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)
        if inside_duration >= GROSS_DWELL_SECONDS:
            text = f"{vehicle_no}  — Gross weight dwell in Weighing Area > {GROSS_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Weighing Area",
                lat,
                lon,
                soc,
                EventIDs.GROSS_WEIGHT_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)


def _check_loading_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
    spv=None,
):
    """Check for loading area dwell overrun."""
    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
    from django.utils import timezone
    
    if state.current_geofence == "Loading Area" and state.last_status == "Stop":
        if inside_duration >= LOADING_DWELL_SECONDS:
            # Check throttling before sending alert
            now_ts = timezone.now()
            if should_throttle_alert(state, 'loading_dwell', now_ts):
                return  # Skip if throttled
            
            text = f"{vehicle_no}  — Loading dwell in Loading Area > {LOADING_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Loading Area",
                lat,
                lon,
                soc,
                EventIDs.LOADING_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)
            
            # Update throttle timestamp
            update_alert_timestamp(state, 'loading_dwell', now_ts)


def _check_tarpaulin_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
    spv=None,
):
    """Check for tarpaulin area dwell overrun."""
    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
    from django.utils import timezone
    
    if state.current_geofence == "Tarpulien" and state.last_status == "Stop":
        if inside_duration >= TARPULIN_DWELL_SECONDS:
            # Check throttling
            now_ts = timezone.now()
            if should_throttle_alert(state, 'tarpaulin_dwell', now_ts):
                return
            
            text = f"{vehicle_no}  — Tarpaulin dwell in Tarpulien > {TARPULIN_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Tarpulien",
                lat,
                lon,
                soc,
                EventIDs.TARPAULIN_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)
            update_alert_timestamp(state, 'tarpaulin_dwell', now_ts)


def _check_maha_border_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
    spv=None,
):
    """Check for Maha border dwell overrun."""
    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
    from django.utils import timezone
    
    if state.current_geofence == "Maha Border":
        if inside_duration >= MAHA_BORDER_DWELL_SECONDS:
            # Check throttling
            now_ts = timezone.now()
            if should_throttle_alert(state, 'maha_border_dwell', now_ts):
                return
            
            text = f"{vehicle_no}  — Maha Border dwell > {MAHA_BORDER_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Maha Border",
                lat,
                lon,
                soc,
                EventIDs.MAHA_BORDER_DWELL,
                text,
            spv=spv,
            )
            alerts_generated.append(a)
            update_alert_timestamp(state, 'maha_border_dwell', now_ts)


def _check_unloading_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
    spv=None,
):
    """Check for unloading area dwell overrun."""
    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
    from django.utils import timezone
    
    if (
        state.current_geofence == "Dhule Circle Geofence"
        and state.last_status == "Stop"
    ):
        if inside_duration >= UNLOADING_DWELL_SECONDS:
            # Check throttling
            now_ts = timezone.now()
            if should_throttle_alert(state, 'unloading_dwell', now_ts):
                return
            
            text = f"{vehicle_no}  — Unloading dwell at Dhule > {UNLOADING_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Dhule Circle Geofence",
                lat,
                lon,
                soc,
                EventIDs.UNLOADING_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)
            update_alert_timestamp(state, 'unloading_dwell', now_ts)


def _check_transit(
    state,
    now_ts,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
    spv=None,
):
    """Check transit SLA compliance."""
    if state.last_departure_ts:
        if state.current_geofence in (D1_JHULWANIA, D2_JHULWANIA, DHULE_GATE):
            travel_seconds = (now_ts - state.last_departure_ts).total_seconds()

            if (
                state.last_departure_geofence == MANAWAR_OUT
                and state.current_geofence == D1_JHULWANIA
            ):
                if (
                    travel_seconds < MANAWAR_TO_JHULWANIA_MIN
                    or travel_seconds > MANAWAR_TO_JHULWANIA_MAX
                ):
                    mins = int(travel_seconds / 60)
                    text = (
                        f"{vehicle_no}  — Transit Manawar→Jhulwania expected "
                        f"{MANAWAR_TO_JHULWANIA_TARGET//60}m±{MANAWAR_TO_JHULWANIA_TOL//60}m actual {mins}m"
                    )
                    a = create_alert_row(
                        vehicle_id,
                        vehicle_no,
                        driver_name,
                        gps_location,
                        state.current_geofence,
                        lat,
                        lon,
                        soc,
                        EventIDs.TRANSIT_BREACH_MANAWAR_JHULWANIA,
                        text,
                    spv=spv,
                    )
                    alerts_generated.append(a)
                state.last_departure_ts = None
                state.last_departure_geofence = None

            if (
                state.last_departure_geofence == D2_JHULWANIA
                and state.current_geofence == DHULE_GATE
            ):
                if (
                    travel_seconds < JHULWANIA_TO_DHULE_MIN
                    or travel_seconds > JHULWANIA_TO_DHULE_MAX
                ):
                    mins = int(travel_seconds / 60)
                    text = (
                        f"{vehicle_no}  — Transit Jhulwania→Dhule expected "
                        f"{JHULWANIA_TO_DHULE_TARGET//60}m±{JHULWANIA_TO_DHULE_TOL//60}m actual {mins}m"
                    )
                    a = create_alert_row(
                        vehicle_id,
                        vehicle_no,
                        driver_name,
                        gps_location,
                        state.current_geofence,
                        lat,
                        lon,
                        soc,
                        EventIDs.TRANSIT_BREACH_JHULWANIA_DHULE,
                        text,
                    spv=spv,
                    )
                    alerts_generated.append(a)
                state.last_departure_ts = None
                state.last_departure_geofence = None


def _check_unplanned_stop(
    state,
    now_ts,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    status,
    alerts_generated,
    throttled_counts,
    spv=None,
):
    """Check for unplanned stop outside geofence with throttling."""
    # Import throttling functions here to avoid circular imports
    from livetracker.alertService.alert_processor import should_throttle_alert, update_alert_timestamp
    
    if status == "Stop":
        if state.stop_start_ts is None:
            state.stop_start_ts = now_ts
        else:
            elapsed_stop = (now_ts - state.stop_start_ts).total_seconds()
            if elapsed_stop >= UNPLANNED_STOP_SECONDS:
                # Check if alert should be throttled
                if should_throttle_alert(state, 'unplanned_stop', now_ts):
                    throttled_counts['unplanned_stop'] = throttled_counts.get('unplanned_stop', 0) + 1
                    return  # Skip this alert due to throttling
                
                text = f"{vehicle_no}  — Unplanned stop outside geofence > {UNPLANNED_STOP_SECONDS//60} min at {lat},{lon}"
                a = create_alert_row(
                    vehicle_id,
                    vehicle_no,
                    driver_name,
                    gps_location,
                    None,
                    lat,
                    lon,
                    soc,
                    EventIDs.UNPLANNED_STOP_OUTSIDE_GEOFENCE,
                    text,
                spv=spv,
                )
                alerts_generated.append(a)
                
                # Update throttling timestamp
                update_alert_timestamp(state, 'unplanned_stop', now_ts)
    else:
        state.stop_start_ts = None


def handle_charging_dwell(
    state,
    now_ts,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
):
    if state.current_geofence and state.last_status == "Charging":
        if state.charging_start_ts is None:
            state.charging_start_ts = now_ts
        else:
            duration = (now_ts - state.charging_start_ts).total_seconds()
            if duration >= CHARGING_OVER_SECONDS:
                text = f"{vehicle_no}  — Charging at {state.current_geofence} > 90 min (entered {state.inside_since.isoformat()})"
                a = create_alert_row(
                    vehicle_id,
                    vehicle_no,
                    driver_name,
                    gps_location,
                    state.current_geofence,
                    lat,
                    lon,
                    soc,
                    EventIDs.CHARGING_OVERRUN,
                    text,
                spv=spv,
                )
                alerts_generated.append(a)
    else:
        state.charging_start_ts = None


def handle_soc_100_stuck(
    state,
    now_ts,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
):
    if soc == 100:
        if state.last_soc != 100:
            state.last_alert_ts = now_ts
        else:
            if state.last_alert_ts:
                if (
                    now_ts - state.last_alert_ts
                ).total_seconds() >= CHARGING_FULL_STUCK_SECONDS:
                    text = f"{vehicle_no}  — SOC=100% for >5 min at {state.current_geofence}"
                    a = create_alert_row(
                        vehicle_id,
                        vehicle_no,
                        driver_name,
                        gps_location,
                        state.current_geofence,
                        lat,
                        lon,
                        soc,
                        EventIDs.CHARGING_FULL_STUCK,
                        text,
                    spv=spv,
                    )
                    alerts_generated.append(a)
    else:
        state.last_alert_ts = None


def handle_weighing_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
):
    if state.current_geofence == "Weighing Area" and state.last_status == "Stop":
        if inside_duration >= TARE_DWELL_SECONDS:
            text = f"{vehicle_no}  — Tare weight dwell in Weighing Area > {TARE_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Weighing Area",
                lat,
                lon,
                soc,
                EventIDs.TARE_WEIGHT_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)
        if inside_duration >= GROSS_DWELL_SECONDS:
            text = f"{vehicle_no}  — Gross weight dwell in Weighing Area > {GROSS_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Weighing Area",
                lat,
                lon,
                soc,
                EventIDs.GROSS_WEIGHT_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)


def handle_loading_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
):
    if state.current_geofence == "Loading Area" and state.last_status == "Stop":
        if inside_duration >= LOADING_DWELL_SECONDS:
            text = f"{vehicle_no}  — Loading dwell in Loading Area > {LOADING_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Loading Area",
                lat,
                lon,
                soc,
                EventIDs.LOADING_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)


def handle_tarpaulin_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
):
    if state.current_geofence == "Tarpulien" and state.last_status == "Stop":
        if inside_duration >= TARPULIN_DWELL_SECONDS:
            text = f"{vehicle_no}  — Tarpaulin dwell in Tarpulien > {TARPULIN_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Tarpulien",
                lat,
                lon,
                soc,
                EventIDs.TARPAULIN_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)


def handle_maha_border_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
):
    if state.current_geofence == "Maha Border":
        if inside_duration >= MAHA_BORDER_DWELL_SECONDS:
            text = f"{vehicle_no}  — Maha Border dwell > {MAHA_BORDER_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Maha Border",
                lat,
                lon,
                soc,
                EventIDs.MAHA_BORDER_DWELL,
                text,
            spv=spv,
            )
            alerts_generated.append(a)


def handle_unloading_dwell(
    state,
    inside_duration,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
):
    if (
        state.current_geofence == "Dhule Circle Geofence"
        and state.last_status == "Stop"
    ):
        if inside_duration >= UNLOADING_DWELL_SECONDS:
            text = f"{vehicle_no}  — Unloading dwell at Dhule > {UNLOADING_DWELL_SECONDS//60} min"
            a = create_alert_row(
                vehicle_id,
                vehicle_no,
                driver_name,
                gps_location,
                "Dhule Circle Geofence",
                lat,
                lon,
                soc,
                EventIDs.UNLOADING_OVERRUN,
                text,
            spv=spv,
            )
            alerts_generated.append(a)


def handle_transit_checks(
    state,
    now_ts,
    vehicle_id,
    vehicle_no,
    driver_name,
    gps_location,
    lat,
    lon,
    soc,
    alerts_generated,
):
    if state.last_departure_ts:
        if state.current_geofence in (D1_JHULWANIA, D2_JHULWANIA, DHULE_GATE):
            travel_seconds = (now_ts - state.last_departure_ts).total_seconds()
            if (
                state.last_departure_geofence == MANAWAR_OUT
                and state.current_geofence == D1_JHULWANIA
            ):
                if (
                    travel_seconds < MANAWAR_TO_JHULWANIA_MIN
                    or travel_seconds > MANAWAR_TO_JHULWANIA_MAX
                ):
                    mins = int(travel_seconds / 60)
                    text = (
                        f"{vehicle_no}  — Transit Manawar→Jhulwania expected "
                        f"{MANAWAR_TO_JHULWANIA_TARGET//60}m±{MANAWAR_TO_JHULWANIA_TOL//60}m actual {mins}m"
                    )
                    a = create_alert_row(
                        vehicle_id,
                        vehicle_no,
                        driver_name,
                        gps_location,
                        state.current_geofence,
                        lat,
                        lon,
                        soc,
                        "transit_breach_manawar_jhulwania",
                        text,
                    spv=spv,
                    )
                    alerts_generated.append(a)
                state.last_departure_ts = None
                state.last_departure_geofence = None
            if (
                state.last_departure_geofence == D2_JHULWANIA
                and state.current_geofence == DHULE_GATE
            ):
                if (
                    travel_seconds < JHULWANIA_TO_DHULE_MIN
                    or travel_seconds > JHULWANIA_TO_DHULE_MAX
                ):
                    mins = int(travel_seconds / 60)
                    text = (
                        f"{vehicle_no}  — Transit Jhulwania→Dhule expected "
                        f"{JHULWANIA_TO_DHULE_TARGET//60}m±{JHULWANIA_TO_DHULE_TOL//60}m actual {mins}m"
                    )
                    a = create_alert_row(
                        vehicle_id,
                        vehicle_no,
                        driver_name,
                        gps_location,
                        state.current_geofence,
                        lat,
                        lon,
                        soc,
                        "transit_breach_jhulwania_dhule",
                        text,
                    spv=spv,
                    )
                    alerts_generated.append(a)
                state.last_departure_ts = None
                state.last_departure_geofence = None
