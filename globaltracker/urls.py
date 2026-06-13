"""
Global Tracker URL Configuration
Uses same API proxy pattern as livetracker
"""
from django.urls import path
from . import views

app_name = 'globaltracker'

urlpatterns = [
    # Main dashboard view
    path('', views.dashboard_view, name='dashboard'),
    
    # Health check endpoint (for debugging)
    path('api/health/', views.health_check, name='health_check'),
    
    # TWINS API proxy endpoints (same as livetracker)
    path(
        "api/twins/latest-points/", 
        views.twins_api_proxy, 
        name="twins_api_proxy"
    ),
    path(
        "api/twins/24hr-route/", 
        views.twins_24hr_route_proxy, 
        name="twins_24hr_route"
    ),

    # Geofence CRUD endpoints
    path('api/geofences/', views.geofences_list_create, name='geofences_list_create'),
    path('api/geofences/<int:pk>/', views.geofence_detail, name='geofence_detail'),
]
