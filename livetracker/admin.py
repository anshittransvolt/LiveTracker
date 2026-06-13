from django.contrib import admin
from django.utils.html import format_html
from .models import VehicleState, VehicleAlert
from .models.livetracker_feedback import Feedback
from .models.alert_record import LiveTrackerAlertAction


@admin.register(VehicleState)
class VehicleStateAdmin(admin.ModelAdmin):
    list_display = [
        "vehicle_no",
        "vehicle_id",
        "driver_name",
        "last_status",
        "current_geofence",
        "last_soc",
        "last_connected",
    ]
    list_filter = ["last_status", "current_geofence", "last_connected"]
    search_fields = ["vehicle_no", "vehicle_id", "driver_name"]
    readonly_fields = [
        "vehicle_id",
        "vehicle_no",
        "driver_name",
        "last_lat",
        "last_lon",
        "last_soc",
        "last_status",
        "last_connected",
        "current_geofence",
        "inside_since",
        "outside_since",
        "stop_start_ts",
        "charging_start_ts",
        "last_departure_ts",
        "last_departure_geofence",
        "last_alert_ts",
    ]
    ordering = ["-last_connected"]

    fieldsets = (
        (
            "Vehicle Information",
            {"fields": ("vehicle_id", "vehicle_no", "driver_name")},
        ),
        (
            "Location & Status",
            {
                "fields": (
                    "last_lat",
                    "last_lon",
                    "last_soc",
                    "last_status",
                    "last_connected",
                )
            },
        ),
        (
            "Geofence Data",
            {"fields": ("current_geofence", "inside_since", "outside_since")},
        ),
        (
            "Tracking Timestamps",
            {
                "fields": (
                    "stop_start_ts",
                    "charging_start_ts",
                    "last_departure_ts",
                    "last_departure_geofence",
                    "last_alert_ts",
                ),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(VehicleAlert)
class VehicleAlertAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "vehicle_no",
        "alert_type",
        "geofence_name",
        "soc",
        "created_at",
        "short_text",
    ]
    list_filter = ["alert_type", "geofence_name", "created_at"]
    search_fields = ["vehicle_no", "vehicle_id", "driver_name", "text"]
    readonly_fields = [
        "vehicle_id",
        "vehicle_no",
        "driver_name",
        "geofence_name",
        "gps_location",
        "lat",
        "lon",
        "soc",
        "alert_type",
        "text",
        "created_at",
    ]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Vehicle Information",
            {"fields": ("vehicle_id", "vehicle_no", "driver_name")},
        ),
        ("Alert Details", {"fields": ("alert_type", "text", "created_at")}),
        (
            "Location Data",
            {"fields": ("geofence_name", "gps_location", "lat", "lon", "soc")},
        ),
    )

    def short_text(self, obj):
        """Display shortened alert text"""
        return obj.text[:60] + "..." if len(obj.text) > 60 else obj.text

    short_text.short_description = "Alert Text"

    actions = ["delete_selected"]

    def has_add_permission(self, request):
        """Prevent manual creation of alerts"""
        return False

    def has_change_permission(self, request, obj=None):
        """Make alerts read-only"""
        return False


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "feedback_type",
        "title",
        "status",
        "reported_by",
        "has_screenshot",
        "created_at",
    ]
    list_filter = ["feedback_type", "status", "created_at", "browser", "os"]
    search_fields = ["title", "description", "reported_by__username"]
    readonly_fields = [
        "created_at",
        "page_url",
        "browser",
        "os",
        "device",
        "reported_by",
        "screenshot_preview",
    ]
    list_editable = ["status"]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Feedback Information",
            {"fields": ("feedback_type", "title", "description", "status")},
        ),
        (
            "Screenshot",
            {"fields": ("screenshot", "screenshot_preview")},
        ),
        (
            "Reporter & Context",
            {
                "fields": (
                    "reported_by",
                    "page_url",
                    "browser",
                    "os",
                    "device",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at",)},
        ),
    )

    def screenshot_preview(self, obj):
        """Display screenshot preview in admin"""
        if obj.screenshot:
            return format_html(
                '<img src="{}" style="max-width: 400px; max-height: 400px; border: 1px solid #ddd; border-radius: 4px;" />',
                obj.screenshot.url
            )
        return "No screenshot uploaded"
    
    screenshot_preview.short_description = "Screenshot Preview"

    def has_screenshot(self, obj):
        """Display if feedback has screenshot"""
        if obj.screenshot:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Yes</span>'
            )
        return format_html(
            '<span style="color: gray;">✗ No</span>'
        )
    
    has_screenshot.short_description = "Screenshot"

    def has_add_permission(self, request):
        """Disable manual addition - feedbacks should come from the form"""
        return False


@admin.register(LiveTrackerAlertAction)
class LiveTrackerAlertActionAdmin(admin.ModelAdmin):
    """Admin interface for Live Alert User Actions"""
    
    list_display = [
        "id",
        "alert_type",
        "vehicle_no",
        "user",
        "action_type_display",
        "action_at",
    ]
    
    list_filter = [
        "action_type",
        "alert_type",
        "action_at",
        "user",
    ]
    
    search_fields = [
        "alert_id",
        "vehicle_no",
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "action_note",
    ]
    
    readonly_fields = [
        "alert_id",
        "alert_type",
        "vehicle_no",
        "user",
        "action_type",
        "action_at",
    ]
    
    ordering = ["-action_at"]
    date_hierarchy = "action_at"
    
    fieldsets = (
        (
            "Alert Information",
            {
                "fields": (
                    "alert_id",
                    "alert_type",
                    "vehicle_no",
                )
            },
        ),
        (
            "User Action Details",
            {
                "fields": (
                    "user",
                    "action_type",
                    "action_note",
                    "action_at",
                )
            },
        ),
    )
    
    def action_type_display(self, obj):
        """Display action type with color coding"""
        colors = {
            "ack": "blue",
            "action": "green",
        }
        color = colors.get(obj.action_type, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_action_type_display()
        )
    
    action_type_display.short_description = "Action Type"
    
    def has_add_permission(self, request):
        """Disable manual addition - actions should come from live alerts"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete for audit trail integrity"""
        return request.user.is_superuser
