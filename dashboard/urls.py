from django.urls import path
from django.shortcuts import redirect
from . import views
from .views.vehicleMaster import vehicles as vehicle_views
from .views import rbac as rbac_views
from .views.feedback_page import update_feedback_status
from .views.api_vehicle_suggestions import vehicle_number_suggestions, validate_vehicle_number
from .views.administration.active_users import active_users
from .views.administration.action_log import user_action_log
from .views.administration.manage_users import (
    manage_users,
    toggle_user_active,
    toggle_user_staff,
    toggle_user_superuser,
    set_user_group,
    update_user_profile,
)
from .views.administration.feedback_view import (
    admin_feedback_list,
    admin_update_feedback_status,
    admin_delete_feedback,
)
from .views.administration.manage_group_access import (
    manage_group_access,
    create_group,
    update_group_projects,
    update_group_pages,
    get_group_access,
)
from .views.ml_model_views.ekf_summary import (
    executive_summary_page,
    api_overview,
    api_fleet_trend,
    api_quintiles,
    api_vehicles,
    api_bayes_coef,
    api_anomaly_tiers,
    api_sessions,
    api_anomaly_breakdown,
    api_soh_bands,
    api_telemetry,
    api_soh_scatter,
)
from .project_routing import build_project_prefixed_path
from .views.utils import set_project

app_name = "dashboard"


def root_redirect(request):
    """Redirect root URL based on authentication status"""
    if request.user.is_authenticated:
        return redirect(
            build_project_prefixed_path(
                "/dashboard/", getattr(request, "project_code", None)
            )
        )
    else:
        return redirect("dashboard:login")


urlpatterns = [
    path("", root_redirect, name="root"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("set-project/", set_project, name="set_project"),
    path("tos/", views.tos, name="tos"),
    path("privacy/", views.privacy, name="privacy"),
    path(
        "forgot-password/",
        views.forgot_password_request,
        name="forgot_password_request",
    ),
    path(
        "forgot-password/verify/",
        views.forgot_password_verify,
        name="forgot_password_verify",
    ),
    path(
        "change-password/",
        views.change_password_request,
        name="change_password_request",
    ),
    path(
        "change-password/verify/",
        views.change_password_verify,
        name="change_password_verify",
    ),
    path("microsoft/login/", views.microsoft_login, name="ms_login"),
    path("microsoft/callback/", views.microsoft_callback, name="ms_callback"),
    path("revision-history/", views.revision_history, name="revision_history"),
    # Notifications API
    path("api/notifications/", views.get_notifications, name="api_notifications"),
    path(
        "api/notifications/<int:notification_id>/read/",
        views.mark_notification_read,
        name="api_mark_notification_read",
    ),
    path(
        "api/notifications/mark-all-read/",
        views.mark_all_read,
        name="api_mark_all_read",
    ),
    # Vehicle API
    path("api/vehicle-suggestions/", vehicle_number_suggestions, name="api_vehicle_suggestions"),
    path("api/validate-vehicle-number/", validate_vehicle_number, name="api_validate_vehicle_number"),
    # RBAC - Project Management
   
    
    # Vehicle Master
    path("vehicles/", vehicle_views.vehicle_list, name="vehicle_list"),
    path(
        "vehicles/<str:registration_number>/",
        vehicle_views.vehicle_detail,
        name="vehicle_detail",
    ),
    path("feedbacklist/", views.view_feedback, name="view_feedback"),
    path(
        "feedback/<int:feedback_id>/update-status/",
        update_feedback_status,
        name="update_feedback_status",
    ),
    # Administration
    path("administration/active-users/", active_users, name="active_users"),
    path("administration/manage-users/", manage_users, name="manage_users"),
    path("administration/manage-users/<int:user_id>/update-profile/", update_user_profile, name="update_user_profile"),
    path("administration/manage-users/<int:user_id>/set-group/", set_user_group, name="set_user_group"),
    path("administration/manage-users/<int:user_id>/toggle-active/", toggle_user_active, name="toggle_user_active"),
    path("administration/manage-users/<int:user_id>/toggle-staff/", toggle_user_staff, name="toggle_user_staff"),
    path("administration/manage-users/<int:user_id>/toggle-superuser/", toggle_user_superuser, name="toggle_user_superuser"),
    path("administration/action-log/user/<int:user_id>/", user_action_log, name="user_action_log"),
    path("administration/manage-group-access/", manage_group_access, name="manage_group_access"),
    path("administration/manage-group-access/create-group/", create_group, name="create_group"),
    path("administration/update-group-projects/<int:group_id>/", update_group_projects, name="update_group_projects"),
    path("administration/update-group-pages/<int:group_id>/", update_group_pages, name="update_group_pages"),
    path("administration/get-group-access/<int:group_id>/", get_group_access, name="get_group_access"),
    path("administration/feedback/", admin_feedback_list, name="admin_feedback_list"),
    path(
        "administration/feedback/<int:feedback_id>/update-status/",
        admin_update_feedback_status,
        name="admin_update_feedback_status",
    ),
    path(
        "administration/feedback/<int:feedback_id>/delete/",
        admin_delete_feedback,
        name="admin_delete_feedback",
    ),
    # ML Models - Executive Summary
    path("ml-models/executive-summary/", executive_summary_page, name="ml_executive_summary"),
    path("api/overview/", api_overview, name="ml_api_overview"),
    path("api/fleet-trend/", api_fleet_trend, name="ml_api_fleet_trend"),
    path("api/quintiles/", api_quintiles, name="ml_api_quintiles"),
    path("api/vehicles/", api_vehicles, name="ml_api_vehicles"),
    path("api/bayes-coef/", api_bayes_coef, name="ml_api_bayes_coef_global"),
    path("api/bayes-coef/<str:reg>/", api_bayes_coef, name="ml_api_bayes_coef_vehicle"),
    path("api/anomaly-tiers/", api_anomaly_tiers, name="ml_api_anomaly_tiers"),
    path("api/sessions/<str:reg>/", api_sessions, name="ml_api_sessions"),
    path("api/anomaly-breakdown/", api_anomaly_breakdown, name="ml_api_anomaly_breakdown"),
    path("api/anomaly-breakdown/<str:reg>/", api_anomaly_breakdown, name="ml_api_anomaly_breakdown_vehicle"),
    path("api/soh-bands/<str:reg>/", api_soh_bands, name="ml_api_soh_bands"),
    path("api/telemetry/<str:reg>/<str:session_id>/", api_telemetry, name="ml_api_telemetry"),
    path("api/soh-scatter/", api_soh_scatter, name="api-soh-scatter"),
    path("access-denied/", views.access_denied, name="access_denied"),
]
