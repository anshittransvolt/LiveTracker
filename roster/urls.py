# urls.py

from django.urls import path
from . import views
from .views import assignments as assignment_views
from .views import drivers as driver_views
from .views import transport as transport_views
from .views import apis as api_views
from .views import active_driver as active_driver_views
from .views import active_vehicle as active_vehicle_views

app_name = "roster"

urlpatterns = [
    path("", assignment_views.assignment_page, name="assignment_page"),
    path("logs/", assignment_views.assignment_logs_page, name="assignment_logs_page"),
    path("drivers/", driver_views.driver_master_page, name="driver_master_page"),
    path("transport/", transport_views.transport_master_page, name="transport_master_page"),
    
    # Reports
    path("reports/active-drivers/", active_driver_views.active_drivers_report, name="active_drivers_report"),
    path("reports/active-vehicles/", active_vehicle_views.active_vehicles_report, name="active_vehicles_report"),
    path("reports/timebox-delay-reasons/", active_driver_views.timebox_delay_reasons_report, name="timebox_delay_reasons_report"),
    
    # Driver management
    path("drivers/<int:driver_id>/edit/", driver_views.driver_edit, name="driver_edit"),
    path(
        "drivers/<int:driver_id>/toggle/",
        driver_views.driver_toggle_active,
        name="driver_toggle_active",
    ),
    # Autocomplete endpoints
    path("autocomplete/horse/", api_views.autocomplete_horse, name="autocomplete_horse"),
    path(
        "autocomplete/trolley/", api_views.autocomplete_trolley, name="autocomplete_trolley"
    ),
    path("autocomplete/driver/", api_views.autocomplete_driver, name="autocomplete_driver"),
    
    # API endpoints
    path("api/drivers/", api_views.get_drivers_api, name="api_drivers"),
    path("api/driver/<str:registration_number>/", api_views.get_driver_by_vehicle_api, name="api_driver_by_vehicle"),
    path("api/assignments/", api_views.check_assignments_api, name="api_check_assignments"),
    path("api/assign-driver/", api_views.assign_driver_api, name="api_assign_driver"),
    path("api/unassign-driver/", api_views.unassign_driver_api, name="api_unassign_driver"),
]
