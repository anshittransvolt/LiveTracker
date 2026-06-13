from django.contrib import admin
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget
from .models import EventType, Event


# ============= RESOURCES =============


class EventTypeResource(resources.ModelResource):
    """Resource for EventType import/export"""

    event_id = fields.Field(column_name="event_id", attribute="event_id")
    event_name = fields.Field(column_name="event_name", attribute="event_name")
    event_description = fields.Field(
        column_name="event_description", attribute="event_description"
    )
    severity = fields.Field(column_name="severity", attribute="severity")

    class Meta:
        model = EventType
        import_id_fields = ["event_id"]
        fields = ("event_id", "event_name", "event_description", "severity")
        export_order = ("event_id", "event_name", "event_description", "severity")


class EventResource(resources.ModelResource):
    """Resource for Event import/export"""

    event_type = fields.Field(
        column_name="event_type",
        attribute="event_type",
        widget=ForeignKeyWidget(EventType, "event_id"),
    )
    created_at = fields.Field(column_name="created_at", attribute="created_at")
    is_active = fields.Field(column_name="is_active", attribute="is_active")

    class Meta:
        model = Event
        import_id_fields = ["id"]
        fields = ("id", "event_type", "created_at", "is_active")
        export_order = ("id", "event_type", "created_at", "is_active")


# ============= ADMIN =============


@admin.register(EventType)
class EventTypeAdmin(ImportExportModelAdmin):
    resource_class = EventTypeResource
    list_display = ("event_id", "event_name", "severity", "created_at")
    list_filter = ("severity", "created_at")
    search_fields = ("event_id", "event_name", "event_description")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("event_id",)

    fieldsets = (
        ("Event Identification", {"fields": ("event_id", "event_name")}),
        ("Event Details", {"fields": ("event_description", "severity")}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


@admin.register(Event)
class EventAdmin(ImportExportModelAdmin):
    resource_class = EventResource
    list_display = (
        "id",
        "get_event_id",
        "get_event_name",
        "get_severity",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "created_at", "event_type__severity")
    search_fields = ("event_type__event_id", "event_type__event_name")
    list_editable = ("is_active",)
    ordering = ("-created_at",)

    def get_event_id(self, obj):
        return obj.event_type.event_id

    get_event_id.short_description = "Event ID"
    get_event_id.admin_order_field = "event_type__event_id"

    def get_event_name(self, obj):
        return obj.event_type.event_name

    get_event_name.short_description = "Event Name"
    get_event_name.admin_order_field = "event_type__event_name"

    def get_severity(self, obj):
        return obj.event_type.severity.upper()

    get_severity.short_description = "Severity"
    get_severity.admin_order_field = "event_type__severity"
