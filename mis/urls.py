from django.urls import path
from . import views

app_name = 'mis'

urlpatterns = [
    path('', views.mis_dashboard, name='dashboard'),
    path('manual/', views.manual_entry, name='manual_entry'),
    path('log/<int:log_id>/', views.log_detail, name='log_detail'),
    path('log/<int:log_id>/edit/', views.log_edit, name='log_edit'),
    path('log/<int:log_id>/delete/', views.log_delete, name='log_delete'),
    path('upload/', views.upload_excel, name='upload_excel'),
    path('templates/manual-logs.xlsx', views.download_manual_template, name='download_manual_template'),
    
    # Report generation URLs
    path('reports/generate/', views.generate_report_view, name='generate_report'),
    path('reports/download/', views.download_report, name='download_report'),
    path('reports/download-incremental/', views.download_report_incremental, name='download_report_incremental'),
    path('reports/calculate/', views.calculate_trips_background, name='calculate_trips'),
    path('reports/calculate-daily/', views.calculate_daily_cache, name='calculate_daily_cache'),
    path('reports/clear-cache/', views.clear_trip_cache, name='clear_trip_cache'),
    
    # Async report generation URLs
    path('reports/generate-async/', views.generate_report_async, name='generate_report_async'),
    path('reports/status/<str:task_id>/', views.report_task_status, name='report_task_status'),
    path('reports/download-async/<str:task_id>/', views.download_async_report, name='download_async_report'),
    
    # API endpoints for cached reports
    path('api/report/status/', views.quick_report_status, name='quick_report_status'),
    path('api/report/download/', views.download_cached_report, name='download_cached_report'),
]
