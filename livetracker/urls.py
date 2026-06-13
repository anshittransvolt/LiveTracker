# livetracker/urls.py
from django.urls import path
from . import views

app_name = "livetracker"

urlpatterns = [
    path("", views.all_view, name="all"),  # /livetracker/
    path(
        "api/analytics/<str:registration_number>/",
        views.vehicle_analytics_api,
        name="analytics_api",
    ),  # /livetracker/api/analytics/<id>/
    path(
        "api/vehicle/<str:registration_number>/historical/",
        views.api_vehicle_historical_data,
        name="vehicle_historical_api",
    ),  # /livetracker/api/vehicle/<id>/historical/?start_date=...&end_date=...
    path(
        "api/geocode/", views.reverse_geocode, name="reverse_geocode"
    ),  # /livetracker/api/geocode/?lat=x&lon=y
    path(
        "api/corridor/", views.corridor_config_api, name="corridor_config_api"
    ),  # /livetracker/api/corridor/
    path(
        "api/drivers/bulk/", views.get_drivers_bulk, name="drivers_bulk"
    ),  # /livetracker/api/drivers/bulk/
    path(
        "api/alerts/", views.get_recent_alerts, name="get_alerts"
    ),  # /livetracker/api/alerts/
    path(
        "api/alerts/deviation/", views.report_deviation_alert, name="report_deviation_alert"
    ),  # /livetracker/api/alerts/deviation/
    # Avg delay time series for TIME BOX
    path(
        "api/timebox/avg-delay-series/",
        views.timebox_avg_delay_series,
        name="timebox_avg_delay_series",
    ),
    # ⚡ OPTIMIZED trend graph API (v2) - uses pre-computed delays from CalculatedTrip
    path(
        "api/timebox/avg-delay-series/v2/",
        views.timebox_avg_delay_series_v2,
        name="timebox_avg_delay_series_v2",
    ),
    # 🆕 Phase-wise delay breakdown API for analytics
    path(
        "api/timebox/phase-breakdown/",
        views.timebox_phase_breakdown_api,
        name="timebox_phase_breakdown",
    ),
    path(
        "api/alerts/<int:alert_id>/seen/", views.mark_alert_seen, name="mark_alert_seen"
    ),  # /livetracker/api/alerts/<id>/seen/
    # TWINS API proxy (avoids CSP issues)
    path(
        "api/twins/latest-points/", views.twins_api_proxy, name="twins_api_proxy"
    ),  # /livetracker/api/twins/latest-points/?limit=5
    path(
        "api/twins/24hr-route/", views.twins_24hr_route_proxy, name="twins_24hr_route"
    ),  # /livetracker/api/twins/24hr-route/?registration_number=ABC123
    # New TIME BOX route (preferred)
    path("timebox/", views.timeline_table_view, name="timebox"),  # /livetracker/timebox/
    # Removed legacy /timeline/ route (migrated to /timebox/)
    path(
        "vehicle/<str:registration_number>/history/<str:date>/", 
        views.vehicle_history_view, 
        name="vehicle_history"
    ),  # /livetracker/vehicle/<id>/history/<date>/
    path("logs/", views.logs_view, name="logs"),  # /livetracker/logs
    path(
        "api/feedback/submit/", views.submit_feedback, name="submit_feedback"
    ),  # /livetracker/api/feedback/submit/
    path("eventpage/", views.event_page_view, name="events"),  # /livetracker/eventpage/
    path(
        "<str:registration_number>/", views.vehicle_view, name="vehicle"
    ),  # /livetracker/<id> - MUST BE LAST (catch-all)
  
    path(
        "api/download_charging_report/<str:registration_number>/",
        views.download_charging_report,
        name="download_charging_report",
    ),
    path(
        "api/download_stoppage_report/<str:registration_number>/",
        views.download_stoppage_report,
        name="download_stoppage_report",
    ),
    path(
        "api/download_dashboard_report/",
        views.dashboard_report_view,
        name="download_dashboard_report",
    ),
]
