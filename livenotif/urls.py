from django.urls import path
from . import views

app_name = "livenotif"

urlpatterns = [
    path("api/toasts/", views.get_active_toasts, name="get_toasts"),
    path("api/alerts/", views.get_latest_alerts, name="get_latest_alerts"),
    path("api/log/", views.log_toast_action, name="log_action"),
]
