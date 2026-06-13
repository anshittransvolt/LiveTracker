"""
Alert Service Package
Monitors vehicle data and generates alerts based on geofence and status rules.
"""

from .alert import alertService

__all__ = ["alertService"]
