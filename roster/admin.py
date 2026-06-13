# admin.py

from django.contrib import admin
from django.core.exceptions import ValidationError
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.results import RowResult
from .models import DriverMaster
from .models import TransportMaster
from .models import HorseTrolleyAssignment
from .models import AssignmentLog


class TransportMasterResource(resources.ModelResource):
    class Meta:
        model = TransportMaster
        skip_unchanged = True
        report_skipped = True
        import_id_fields = ["horse_chassis_no"]
        fields = (
            "transport_name",
            "horse_chassis_no",
            "horse_number",
            "trolley_number",
            "trolley_chassis_no",
        )

    def before_import_row(self, row, **kwargs):
        """Clean and validate data before import"""
        if "horse_chassis_no" in row:
            row["horse_chassis_no"] = str(row["horse_chassis_no"]).strip().upper()
        if "horse_number" in row:
            row["horse_number"] = str(row["horse_number"]).strip().upper()

        if "trolley_number" in row and row["trolley_number"]:
            row["trolley_number"] = str(row["trolley_number"]).strip().upper()
        if "trolley_chassis_no" in row and row["trolley_chassis_no"]:
            row["trolley_chassis_no"] = str(row["trolley_chassis_no"]).strip().upper()

    def skip_row(self, instance, original, row, import_validation_errors=None):
        """Skip if record already exists with same data"""
        if original and original.pk:
            if (
                original.horse_number == instance.horse_number
                and original.trolley_number == instance.trolley_number
                and original.trolley_chassis_no == instance.trolley_chassis_no
            ):
                return True

        existing_chassis = (
            TransportMaster.objects.filter(horse_chassis_no=instance.horse_chassis_no)
            .exclude(pk=instance.pk if instance.pk else None)
            .first()
        )

        if existing_chassis:
            if import_validation_errors is not None:
                import_validation_errors[0] = ValidationError(
                    f"Horse chassis number {instance.horse_chassis_no} already exists"
                )
            return True

        existing_horse = (
            TransportMaster.objects.filter(horse_number=instance.horse_number)
            .exclude(pk=instance.pk if instance.pk else None)
            .first()
        )

        if existing_horse:
            if import_validation_errors is not None:
                import_validation_errors[0] = ValidationError(
                    f"Horse number {instance.horse_number} already exists"
                )
            return True

        return super().skip_row(instance, original, row, import_validation_errors)


class DriverMasterResource(resources.ModelResource):
    class Meta:
        model = DriverMaster
        skip_unchanged = True
        report_skipped = True
        import_id_fields = ["employee_code"]
        fields = ("employee_code", "employee_name", "phone", "ultratech_id", "is_active")
        export_order = ("employee_code", "employee_name", "phone", "ultratech_id", "is_active")

    def before_import_row(self, row, **kwargs):
        """Clean and validate data before import"""
        # Required fields
        if "employee_code" in row:
            row["employee_code"] = str(row["employee_code"]).strip().upper()
        if "employee_name" in row:
            row["employee_name"] = str(row["employee_name"]).strip().title()

        # Optional fields - set to None/default if empty
        if "phone" in row:
            phone = str(row["phone"]).strip() if row["phone"] else None
            row["phone"] = phone if phone else None
        else:
            row["phone"] = None

        if "is_active" not in row or row["is_active"] == "":
            row["is_active"] = True
        else:
            # Handle various true/false representations
            is_active_str = str(row["is_active"]).strip().lower()
            row["is_active"] = is_active_str in ["true", "1", "yes", "active"]

    def skip_row(self, instance, original, row, import_validation_errors=None):
        """Skip if record already exists with same data"""
        if original and original.pk:
            if (
                original.employee_name == instance.employee_name
                and original.phone == instance.phone
                and original.is_active == instance.is_active
            ):
                return True

        existing = (
            DriverMaster.objects.filter(employee_code=instance.employee_code)
            .exclude(pk=instance.pk if instance.pk else None)
            .first()
        )

        if existing:
            if import_validation_errors is not None:
                import_validation_errors[0] = ValidationError(
                    f"Employee code {instance.employee_code} already exists"
                )
            return True

        return super().skip_row(instance, original, row, import_validation_errors)


@admin.register(TransportMaster)
class TransportMasterAdmin(ImportExportModelAdmin):
    resource_class = TransportMasterResource
    list_display = (
        "horse_number",
        "trolley_number",
        "horse_chassis_no",
        "trolley_chassis_no",
    )
    search_fields = ("horse_number", "trolley_number", "horse_chassis_no")
    list_filter = ("transport_name",)
    ordering = ("horse_number",)  # Add ordering for autocomplete

    def save_model(self, request, obj, form, change):
        """Validate before saving"""
        try:
            obj.full_clean()
            super().save_model(request, obj, form, change)
        except ValidationError as e:
            form.add_error(None, e)


@admin.register(DriverMaster)
class DriverMasterAdmin(ImportExportModelAdmin):
    resource_class = DriverMasterResource
    list_display = (
        "employee_name",
        "employee_code",
        "phone",
        "ultratech_id",
        "is_active",
        "created_at",
    )
    search_fields = ("employee_code", "employee_name", "ultratech_id")
    list_filter = ("is_active", "created_at")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("employee_code",)  # Add ordering for autocomplete

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("employee_code", "employee_name", "phone", "ultratech_id", "is_active")},
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def save_model(self, request, obj, form, change):
        """Validate before saving"""
        try:
            obj.full_clean()
            super().save_model(request, obj, form, change)
        except ValidationError as e:
            form.add_error(None, e)


@admin.register(HorseTrolleyAssignment)
class HorseTrolleyAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "get_horse_number",
        "get_driver_name",
        "get_driver_code",
        "route",
        "place",
        "lr_number",
        "tonnage",
        "assigned_date",
    )
    search_fields = ("horse__horse_number", "driver__employee_code", "driver__employee_name", "lr_number")
    list_filter = ("assigned_date", "driver__is_active", "route", "place")
    readonly_fields = ("assigned_date",)
    autocomplete_fields = ['horse', 'driver']  # Enable autocomplete for ForeignKey fields
    fields = ('horse', 'driver', 'route', 'place', 'lr_number', 'tonnage', 'assigned_date')
    
    def get_horse_number(self, obj):
        return obj.horse.horse_number if obj.horse else None
    get_horse_number.short_description = 'Horse Number'
    get_horse_number.admin_order_field = 'horse__horse_number'
    
    def get_driver_name(self, obj):
        return obj.driver.employee_name if obj.driver else None
    get_driver_name.short_description = 'Driver Name'
    get_driver_name.admin_order_field = 'driver__employee_name'
    
    def get_driver_code(self, obj):
        return obj.driver.employee_code if obj.driver else None
    get_driver_code.short_description = 'Driver Code'
    get_driver_code.admin_order_field = 'driver__employee_code'

    def save_model(self, request, obj, form, change):
        """Validate before saving"""
        try:
            obj.full_clean()
            super().save_model(request, obj, form, change)
        except ValidationError as e:
            form.add_error(None, e)



@admin.register(AssignmentLog)
class AssignmentLogAdmin(admin.ModelAdmin):
    list_display = (
        'performed_at',
        'action',
        'horse_number',
        'driver_name',
        'driver_code',
        'route',
        'place',
        'lr_number',
        'tonnage',
        'get_performed_by',
        'ip_address',
    )
    list_filter = ('action', 'performed_at', 'route', 'place')
    search_fields = (
        'horse_number',
        'driver_name',
        'driver_code',
        'lr_number',
        'performed_by__username',
        'ip_address',
    )
    readonly_fields = (
        'horse_number',
        'driver_code',
        'driver_name',
        'route',
        'place',
        'lr_number',
        'tonnage',
        'action',
        'performed_by',
        'performed_at',
        'ip_address',
        'previous_driver_code',
        'previous_driver_name',
        'notes',
    )
    date_hierarchy = 'performed_at'
    
    def get_performed_by(self, obj):
        return obj.performed_by.username if obj.performed_by else 'System'
    get_performed_by.short_description = 'Performed By'
    get_performed_by.admin_order_field = 'performed_by__username'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


from .models import TimeboxReason

@admin.register(TimeboxReason)
class TimeboxReasonAdmin(admin.ModelAdmin):
    list_display = (
        'vehicle_number',
        'driver_name',
        'driver_phone',
        'reason_preview',
        'logged_by',
        'logged_at',
    )
    list_filter = ('logged_at', 'vehicle_number')
    search_fields = ('vehicle_number', 'driver_name', 'driver_phone', 'reason')
    readonly_fields = ('logged_at', 'logged_by')
    date_hierarchy = 'logged_at'
    ordering = ('-logged_at',)
    
    def reason_preview(self, obj):
        return obj.reason[:50] + '...' if len(obj.reason) > 50 else obj.reason
    reason_preview.short_description = 'Reason'
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
