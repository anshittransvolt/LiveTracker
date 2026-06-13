from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget, Widget
from decimal import Decimal, InvalidOperation
from .models import ModelType, Vendor, ModelImage, ModelSpecification, Vehicle

from import_export import resources, fields
from datetime import datetime
from dateutil.parser import parse
class CleanCharWidget(Widget):
    """Custom widget to handle empty/invalid char values gracefully"""
    
    def clean(self, value, row=None, *args, **kwargs):
        if not value or value in ('', None, 'None', 'null', 'NULL', 'N/A', '-'):
            return None
        return str(value).strip()

    def render(self, value, obj=None, **kwargs):
        return value or ''


class VendorResource(resources.ModelResource):
    class Meta:
        model = Vendor
        import_id_fields = ["vendor_name"]
        fields = (
            "vendor_name",
            "vendor_support_email",
            "transvolt_contact_email",
            "transvolt_contact_person_mobile_no",
            "vendor_support_site",
            "details",
        )


class ModelTypeResource(resources.ModelResource):
    vendor = fields.Field(
        column_name="vendor",
        attribute="vendor",
        widget=ForeignKeyWidget(Vendor, "vendor_name"),
    )

    class Meta:
        model = ModelType
        import_id_fields = ["model_number"]
        fields = ("vendor", "model_number", "category", "created_at")


class ModelSpecificationResource(resources.ModelResource):
    model_type = fields.Field(
        column_name="model_type",
        attribute="model_type",
        widget=ForeignKeyWidget(ModelType, "model_number"),
    )

    class Meta:
        model = ModelSpecification
        import_id_fields = ["model_type"]
        fields = ("model_type", "specs")


class ModelImageResource(resources.ModelResource):
    model_type = fields.Field(
        column_name="model_type",
        attribute="model_type",
        widget=ForeignKeyWidget(ModelType, "model_number"),
    )

    class Meta:
        model = ModelImage
        import_id_fields = ["id"]
        fields = ("model_type", "image", "uploaded_at")


class VehicleResource(resources.ModelResource):
    vehicle_registration_date = fields.Field(
        attribute="vehicle_registration_date",
        column_name="vehicle_registration_date"
    )

    class Meta:
        model = Vehicle
        import_id_fields = ("registration_number",)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
       
        project_name = row.get("project_name")
        if project_name:
            row["project_name"] = str(project_name).strip()

        
        depot = row.get("depot")
        if depot:
            row["depot"] = str(depot).strip()

       
        raw_date = row.get("vehicle_registration_date")
        if raw_date:
            row["vehicle_registration_date"] = self.parse_date(raw_date)

    def parse_date(self, value):
        if not value:
            return None

        value = str(value).strip()

        formats = [
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except:
                continue

        try:
            return parse(value).date()
        except Exception:
            raise ValueError(f"Invalid date format: {value}")