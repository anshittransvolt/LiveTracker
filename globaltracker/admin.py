from django.contrib import admin
from .models import Geofence


@admin.register(Geofence)
class GeofenceAdmin(admin.ModelAdmin):
    list_display = ['name', 'spv', 'created_by', 'created_at']
    list_filter = ['spv', 'created_at']
    search_fields = ['name', 'spv']
    readonly_fields = ['created_at', 'updated_at']
