from django.contrib import admin
import json
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from import_export.admin import ImportExportModelAdmin
from .models import (
    UserProfile,
    RevisionHistory,
    Notification,
    ModelType,
    Vendor,
    ModelImage,
    ModelSpecification,
    Vehicle,
    ApiAuth,
)
from .models.rbac.group_access import GroupAccess
from .models.rbac.page import Page
from .models.rbac.projects import Project
from .models.user_action_log import UserActionLog
from .forms import SpecificationAdminForm, VendorAdminForm
from .resources import (
    VendorResource,
    ModelTypeResource,
    ModelSpecificationResource,
    ModelImageResource,
    VehicleResource,
)


class UserProfileInline(admin.StackedInline):
    """Inline admin for UserProfile - shows profile fields within User admin"""

    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile Information"
    fields = ("msal_connected", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


class ExtendedUserAdmin(BaseUserAdmin):
    """Extended User admin that displays all user fields plus profile fields"""

    inlines = (UserProfileInline,)

    # Display user fields + profile information in list view
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "get_msal_connected",
        "get_auth_method",
        "date_joined",
    )

    # Add profile-based filters
    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "profile__msal_connected",
        "date_joined",
    )

    # Search across user and profile fields
    search_fields = ("username", "first_name", "last_name", "email")

    def get_msal_connected(self, obj):
        """Display MSAL connection status"""
        if hasattr(obj, "profile"):
            return obj.profile.msal_connected
        return False

    get_msal_connected.boolean = True
    get_msal_connected.short_description = "MSAL Connected"

    def get_auth_method(self, obj):
        """Display authentication method"""
        if hasattr(obj, "profile"):
            return obj.profile.auth_method
        return "Unknown"

    get_auth_method.short_description = "Auth Method"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Dedicated admin for UserProfile that shows all user + profile data"""

    # Display all relevant user and profile fields
    list_display = (
        "get_username",
        "get_email",
        "get_first_name",
        "get_last_name",
        "group",
        "msal_connected",
        "get_auth_method",
        "created_at",
        "updated_at",
    )

    # Filters for profile and user data
    list_filter = (
        "group",
        "msal_connected",
        "created_at",
        "user__is_active",
        "user__is_staff",
        "user__date_joined",
    )

    # Search across user fields through the relationship
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "group__name",
    )

    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)

    fieldsets = (
        (
            "User Information",
            {"fields": ("user",), "description": "Associated Django user account"},
        ),
        (
            "Group & Access Control",
            {
                "fields": ("group",),
                "description": "Assign user to a group to control project and page access",
            },
        ),
        (
            "Authentication Details",
            {
                "fields": ("msal_connected",),
                "description": "Track how the user was created/authenticated",
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    # Methods to display user fields in UserProfile admin
    def get_username(self, obj):
        return obj.user.username

    get_username.short_description = "Username"
    get_username.admin_order_field = "user__username"

    def get_email(self, obj):
        return obj.user.email

    get_email.short_description = "Email"
    get_email.admin_order_field = "user__email"

    def get_first_name(self, obj):
        return obj.user.first_name

    get_first_name.short_description = "First Name"
    get_first_name.admin_order_field = "user__first_name"

    def get_last_name(self, obj):
        return obj.user.last_name

    get_last_name.short_description = "Last Name"
    get_last_name.admin_order_field = "user__last_name"

    def get_auth_method(self, obj):
        return obj.auth_method

    get_auth_method.short_description = "Auth Method"


# Unregister default User admin and register our extended version
admin.site.unregister(User)
admin.site.register(User, ExtendedUserAdmin)


class VehicleImageInline(admin.TabularInline):
    model = ModelImage
    extra = 0
    max_num = 2
    readonly_fields = ("uploaded_at", "image_preview")
    fields = ("image", "image_preview", "uploaded_at")

    def image_preview(self, obj):
        """Display a compact preview of the uploaded image"""
        if obj.image:
            return format_html(
                '<img src="{}" style="max-width: 150px; max-height: 100px; '
                'object-fit: cover; border-radius: 4px; border: 1px solid #ddd;" />',
                obj.image.url,
            )
        return "No image"

    image_preview.short_description = "Preview"


class SpecificationInline(admin.StackedInline):
    model = ModelSpecification
    form = SpecificationAdminForm
    can_delete = False
    max_num = 1
    verbose_name = "Specification"
    verbose_name_plural = "Specifications"


@admin.register(ModelType)
class VehicleTypeAdmin(ImportExportModelAdmin):
    resource_class = ModelTypeResource
    list_display = ("vendor", "model_number", "category", "created_at")
    search_fields = ("model_number", "vendor__vendor_name")
    list_filter = ("category", "vendor")
    inlines = (SpecificationInline, VehicleImageInline)


@admin.register(Vendor)
class VendorAdmin(ImportExportModelAdmin):
    resource_class = VendorResource
    form = VendorAdminForm
    list_display = (
        "vendor_name",
        "vendor_support_email",
        "transvolt_contact_email",
        "transvolt_contact_person_mobile_no",
        "vendor_support_site",
        "get_details",
    )
    search_fields = (
        "vendor_name",
        "vendor_support_email",
        "transvolt_contact_email",
        "transvolt_contact_person_mobile_no",
    )

    def get_details(self, obj):
        """Return a short human-readable summary of the JSON `details` field.

        Similar to the Specification summary: show up to 4 key:value pairs for dicts
        or up to 6 items for lists. Empty -> blank.
        """
        raw = getattr(obj, "details", None)
        if raw is None:
            return ""

        data = raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except Exception:
                data = raw

        try:
            if isinstance(data, dict):
                parts = []
                for i, (k, v) in enumerate(data.items()):
                    if i >= 4:
                        parts.append("...")
                        break
                    parts.append(f"{k}: {v}")
                return "; ".join(parts)

            if isinstance(data, (list, tuple)):
                parts = [str(x) for x in data[:6]]
                if len(data) > 6:
                    parts.append("...")
                return ", ".join(parts)

            s = str(data)
            return (s[:200] + "...") if len(s) > 200 else s
        except Exception:
            s = str(raw)
            return (s[:200] + "...") if len(s) > 200 else s

    get_details.short_description = "Details"


@admin.register(ModelImage)
class VehicleImageAdmin(ImportExportModelAdmin):
    resource_class = ModelImageResource
    list_display = ("model_type", "image_preview", "image", "uploaded_at")
    readonly_fields = ("uploaded_at", "image_preview_large")
    search_fields = ("model_type__model_number",)
    fields = ("model_type", "image", "image_preview_large", "uploaded_at")

    def image_preview(self, obj):
        """Display a small preview thumbnail in list view"""
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 60px; height: 40px; '
                'object-fit: cover; border-radius: 4px; border: 1px solid #ddd;" />',
                obj.image.url,
            )
        return "No image"

    image_preview.short_description = "Preview"

    def image_preview_large(self, obj):
        """Display a larger preview in detail view"""
        if obj.image:
            return format_html(
                '<img src="{}" style="max-width: 400px; max-height: 300px; '
                "object-fit: contain; border-radius: 8px; border: 2px solid #ddd; "
                'box-shadow: 0 2px 4px rgba(0,0,0,0.1);" />',
                obj.image.url,
            )
        return "No image uploaded"

    image_preview_large.short_description = "Image Preview"


@admin.register(ModelSpecification)
class SpecificationAdmin(ImportExportModelAdmin):
    resource_class = ModelSpecificationResource
    form = SpecificationAdminForm
    list_display = ("model_type", "get_specs")
    search_fields = ("model_type__model_number",)

    def get_specs(self, obj):
        """Return a compact, human-readable summary of the JSON specs.

        - If `specs` is a dict, show up to 4 key: value pairs joined by `; `.
        - If `specs` is a list, show up to 6 items joined by `, `.
        - Otherwise, fallback to truncated string representation.
        """
        raw = getattr(obj, "specs", None)
        if raw is None:
            return ""

        # If the field is already a Python object, use it; otherwise try to parse JSON.
        data = raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except Exception:
                data = raw

        try:
            # dict -> key: val; ...
            if isinstance(data, dict):
                parts = []
                for i, (k, v) in enumerate(data.items()):
                    if i >= 4:
                        parts.append("...")
                        break
                    # stringify simple values
                    parts.append(f"{k}: {v}")
                return "; ".join(parts)

            # list/tuple -> comma separated
            if isinstance(data, (list, tuple)):
                parts = [str(x) for x in data[:6]]
                if len(data) > 6:
                    parts.append("...")
                return ", ".join(parts)

            # fallback to string
            s = str(data)
            return (s[:200] + "...") if len(s) > 200 else s
        except Exception:
            # defensive fallback
            s = str(raw)
            return (s[:200] + "...") if len(s) > 200 else s

    get_specs.short_description = "Specs"


@admin.register(RevisionHistory)
class RevisionHistoryAdmin(admin.ModelAdmin):
    """Admin for RevisionHistory that auto-fills created_by and version.

    - If a user creates a RevisionHistory via the admin, `created_by` will be set
      to the logged-in user when saving (if not already set).
    - If `version` is blank on creation, it will be computed from the latest
      RevisionHistory using the model helper `next_version()`.
    """

    list_display = (
        "version",
        "title",
        "created_by_email",
        "is_published",
        "created_at",
    )
    # Keep only timestamps readonly; allow admins to edit version and created_by_email (prefilled).
    readonly_fields = ("created_at",)
    search_fields = ("version", "title", "description", "created_by_email")
    list_filter = ("is_published", "created_at")
    # Single, plain form (no tabs). Show version and created_by_email as editable inputs
    # prefilled in add view so admins can override them if needed.
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "version",
                    "created_by_email",
                    "title",
                    "description",
                    "is_published",
                    "effective_date",
                    "created_at",
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        # Ensure FK link to current user is set so we can retain relational info.
        try:
            obj.created_by = request.user
        except Exception:
            obj.created_by = None

        # Respect any value the admin provided for created_by_email in the form; if
        # they left it blank, default to request.user.email.
        try:
            form_email = None
            if form is not None:
                form_email = (
                    form.cleaned_data.get("created_by_email")
                    if hasattr(form, "cleaned_data")
                    else None
                )
            if form_email:
                obj.created_by_email = form_email
            else:
                obj.created_by_email = request.user.email or None
        except Exception:
            # leave as-is if something goes wrong
            pass

        # Compute version only if not provided by the admin form (allow overrides).
        if not getattr(obj, "version", None):
            try:
                obj.version = obj.__class__.next_version()
            except Exception:
                if not obj.version:
                    obj.version = "1.0.0"

        super().save_model(request, obj, form, change)

    def get_changeform_initial_data(self, request):
        """Provide initial values for the add form so readonly fields show expected values.

        - `version` is shown as the next semantic version (1.0.0 style).
        - `created_by_email` is prefilled with the logged-in user's email.
        """
        initial = super().get_changeform_initial_data(request) or {}
        try:
            initial["version"] = RevisionHistory.next_version()
        except Exception:
            initial["version"] = "1.0.0"

        try:
            initial["created_by_email"] = request.user.email or ""
        except Exception:
            initial["created_by_email"] = ""

        return initial


@admin.register(Vehicle)
class VehicleAdmin(ImportExportModelAdmin):
    """Admin for the Vehicle master table.

    Provides a compact table view with useful search, filters and read-only
    timestamp. Shows related vehicle type and vendor (via method) for convenience.
    """

    resource_class = VehicleResource
    list_display = (
        "registration_number",
        "project_name",
        "company_name",
        "model",
        "vehicle_type",
        "get_vendor_name",
        "location",
        "depot",
        "seating_capacity",
        "battery_capacity",
        "updated_date",
    )
    search_fields = (
        "registration_number",
        "chassis_number",
        "motor_no",
        "mac_id",
        "project_name",
        "company_name",
        "location",
        "depot",
        "model__model_number",
        "model__vendor__vendor_name",
    )
    list_filter = (
        "project_name",
        "company_name",
        "vehicle_category",
        "model",
        "vehicle_type",
        "location",
        "depot",
        "battery_type",
    )
    readonly_fields = ("updated_date",)
    ordering = ("-updated_date",)
    
    def get_vendor_name(self, obj):
        """Display vendor name from related model."""
        return obj.model.vendor.vendor_name if obj.model and obj.model.vendor else "--"
    get_vendor_name.short_description = "Vendor"
    get_vendor_name.admin_order_field = "model__vendor__vendor_name"
    
    fieldsets = (
        ("Project & Company Information", {
            "fields": ("project_name", "company_name", "location", "depot"),
        }),
        ("Vehicle Identification", {
            "fields": ("registration_number", "chassis_number", "motor_no", "mac_id"),
        }),
        ("Vehicle Details", {
            "fields": ("model", "vehicle_type", "vehicle_category", "seating_capacity", "length", "vehicle_registration_date"),
        }),
        ("Battery Information", {
            "fields": ("battery_type", "battery_capacity"),
        }),
        ("Metadata", {
            "fields": ("updated_date",),
            "classes": ("collapse",),
        }),
    )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Admin for managing notifications"""

    list_display = ("title", "user", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read", "created_at")
    search_fields = ("title", "message", "user__username", "user__email")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    fieldsets = (
        (
            "Notification Details",
            {"fields": ("user", "title", "message", "notification_type")},
        ),
        ("Additional Info", {"fields": ("link", "is_read", "created_at")}),
    )

    actions = ["mark_as_read", "mark_as_unread"]

    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f"{updated} notification(s) marked as read.")

    mark_as_read.short_description = "Mark selected notifications as read"

    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False)
        self.message_user(request, f"{updated} notification(s) marked as unread.")

    mark_as_unread.short_description = "Mark selected notifications as unread"


@admin.register(ApiAuth)
class ApiAuthAdmin(admin.ModelAdmin):
    """Admin for API Authentication - manages API access keys"""

    list_display = (
        "username",
        "access_key_display",
        "ttl_display",
        "created_at",
        "updated_at",
    )
    list_filter = ("ttl", "created_at")
    search_fields = ("username", "access_key")
    readonly_fields = ("access_key", "created_at", "updated_at")
    ordering = ("-created_at",)

    fieldsets = (
        (
            "Authentication Details",
            {
                "fields": ("username", "access_key", "ttl"),
                "description": "Access key is automatically generated when creating a new user.",
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    actions = ["regenerate_keys"]

    def access_key_display(self, obj):
        """Display access key with copy-friendly format"""
        return format_html(
            '<code style="background: #f4f4f4; padding: 4px 8px; border-radius: 3px; font-family: monospace;">{}</code>',
            obj.access_key,
        )

    access_key_display.short_description = "Access Key"

    def ttl_display(self, obj):
        """Display expiration date/time or 'No Expiration'"""
        if obj.ttl is None:
            return format_html(
                '<span style="color: green; font-weight: bold;">No Expiration</span>'
            )
        else:
            from django.utils import timezone
            now = timezone.now()
            if obj.ttl < now:
                return format_html(
                    '<span style="color: red; font-weight: bold;">{}</span>',
                    obj.ttl.strftime("%Y-%m-%d %H:%M")
                )
            else:
                return format_html(
                    '<span style="color: orange;">{}</span>',
                    obj.ttl.strftime("%Y-%m-%d %H:%M")
                )

    ttl_display.short_description = "ttl"

    def regenerate_keys(self, request, queryset):
        """Action to regenerate access keys for selected users"""
        count = 0
        for obj in queryset:
            obj.access_key = obj.generate_access_key()
            obj.save(update_fields=["access_key", "updated_at"])
            count += 1
        self.message_user(request, f"Regenerated {count} access key(s).")

    regenerate_keys.short_description = "Regenerate access keys for selected users"

    def save_model(self, request, obj, form, change):
        """Override to show message when new access key is created"""
        if not change:  # New object
            super().save_model(request, obj, form, change)
            self.message_user(
                request,
                f"Access key created: {obj.access_key} (save this - it won't be shown again)",
                level="success",
            )
        else:
            super().save_model(request, obj, form, change)


@admin.register(Page)
class PageAdmin(ImportExportModelAdmin):
    """Admin for Pages - defines accessible pages/views in the system"""
    
    list_display = ('code', 'name', 'section', 'project')
    search_fields = ('code', 'name', 'section', 'project')
    ordering = ('code',)
    
    fieldsets = (
        ('Page Information', {
            'fields': ('code', 'name'),
            'description': 'Pages represent different views or sections users can access.'
        }),
        ('Optional Fields', {
            'fields': ('section', 'project'),
            'classes': ('collapse',),
            'description': 'Optional grouping and project association fields.'
        }),
    )


@admin.register(Project)
class ProjectAdmin(ImportExportModelAdmin):
    """Admin for Projects - main organizational unit"""
    
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)
    ordering = ('name',)
    
    fieldsets = (
        ('Project Information', {
            'fields': ('name', 'is_active'),
        }),
    )


@admin.register(GroupAccess)
class GroupAccessAdmin(admin.ModelAdmin):
    """Admin for Group Access configuration"""
    
    list_display = ('group', 'project_count', 'page_count', 'created_at', 'updated_at')
    search_fields = ('group__name',)
    ordering = ('group__name',)
    readonly_fields = ('created_at', 'updated_at')
    filter_horizontal = ('projects', 'pages')
    
    fieldsets = (
        ('Group Information', {
            'fields': ('group',),
        }),
        ('Access Configuration', {
            'fields': ('projects', 'pages'),
        }),
        ('Additional Settings', {
            'fields': ('access',),
            'description': 'Optional: Additional access configuration as JSON'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def project_count(self, obj):
        """Display number of projects this group has access to"""
        return obj.projects.count()
    project_count.short_description = 'Projects'
    
    def page_count(self, obj):
        """Display number of pages this group has access to"""
        return obj.pages.count()
    page_count.short_description = 'Pages'


@admin.register(UserActionLog)
class UserActionLogAdmin(admin.ModelAdmin):
    """
    Admin interface for viewing user action logs.
    Read-only to preserve audit trail integrity.
    """
    
    list_display = (
        'created_at',
        'user',
        'role',
        'action',
        'method',
        'response_status',
        'duration_ms',
        'ip_address',
    )
    
    list_filter = (
        'created_at',
        'role',
        'method',
        'response_status',
        'section',
    )
    
    search_fields = (
        'user__username',
        'user__email',
        'action',
        'path',
        'ip_address',
        'session_id',
    )
    
    readonly_fields = (
        'user',
        'role',
        'ip_address',
        'user_agent',
        'session_id',
        'section',
        'action',
        'path',
        'method',
        'response_status',
        'duration_ms',
        'session_duration',
        'created_at',
    )
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'role', 'ip_address')
        }),
        ('Request Details', {
            'fields': ('method', 'path', 'section', 'action')
        }),
        ('Response & Performance', {
            'fields': ('response_status', 'duration_ms')
        }),
        ('Session Information', {
            'fields': ('session_id', 'session_duration')
        }),
        ('Technical Details', {
            'fields': ('user_agent',),
            'classes': ('collapse',)
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )
    
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    # Disable add/change/delete to preserve audit trail
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Only superusers can delete logs (for cleanup purposes)
        return request.user.is_superuser

