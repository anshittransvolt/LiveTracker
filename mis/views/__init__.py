"""
MIS Views Package
=================
Organized views split by functionality for better maintainability.
"""

# Dashboard views
from .dashboard_views import mis_dashboard

# Daily log management views
from .log_views import (
    manual_entry,
    log_detail, 
    log_edit,
    log_delete
)

# Report generation views
from .report_views import (
    generate_report_view,
    download_report,
    download_report_incremental,
    generate_report_async,
    report_task_status,
    download_async_report
)

# Cache and calculation views
from .cache_views import (
    calculate_daily_cache,
    calculate_trips_background,
    clear_trip_cache
)

# API endpoints
from .api_views import (
    quick_report_status,
    download_cached_report
)

# File handling views
from .file_views import (
    upload_excel,
    download_manual_template
)

__all__ = [
    # Dashboard
    'mis_dashboard',
    
    # Daily logs
    'manual_entry',
    'log_detail',
    'log_edit', 
    'log_delete',
    
    # Reports
    'generate_report_view',
    'download_report',
    'download_report_incremental',
    'generate_report_async',
    'report_task_status',
    'download_async_report',
    
    # Cache
    'calculate_daily_cache',
    'calculate_trips_background',
    'clear_trip_cache',
    
    # API
    'quick_report_status',
    'download_cached_report',
    
    # Files
    'upload_excel',
    'download_manual_template',
]