from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
import json
from dashboard.models import Vehicle
from dashboard.project_routing import get_default_project_code, normalize_project_code


def _normalize_spec_value(value):
    """Normalize spec values by parsing nested JSON strings recursively."""
    if isinstance(value, str):
        raw = value.strip()
        if raw and raw[0] in "[{":
            try:
                parsed = json.loads(raw)
                return _normalize_spec_value(parsed)
            except (json.JSONDecodeError, TypeError, ValueError):
                return value
        return value

    if isinstance(value, dict):
        return {str(k): _normalize_spec_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_normalize_spec_value(item) for item in value]

    return value


def _flatten_spec_items(value, prefix=""):
    """Flatten nested spec objects into key/value pairs for display/export."""
    items = []

    if isinstance(value, dict):
        for key, nested_value in value.items():
            label = f"{prefix} > {key}" if prefix else str(key)
            items.extend(_flatten_spec_items(nested_value, label))
        return items

    if isinstance(value, list):
        if all(not isinstance(item, (dict, list, tuple)) for item in value):
            items.append((prefix or "Value", ", ".join(str(item) for item in value)))
            return items

        for index, nested_value in enumerate(value, start=1):
            label = f"{prefix} > {index}" if prefix else str(index)
            items.extend(_flatten_spec_items(nested_value, label))
        return items

    items.append((prefix or "Value", str(value)))
    return items


@login_required
def vehicle_list(request):
    """Display list of all vehicles with sortable columns.

    Supports sorting via GET param 'sort' (e.g. ?sort=registration_number or ?sort=-depot).
    Prefetches related model, vendor, and images for efficient queries.
    """
    # Get sort parameter from query string
    sort_by = request.GET.get("sort", "-updated_date")  # default: newest first

    # Valid sortable fields (protect against SQL injection)
    valid_sorts = [
        "registration_number",
        "-registration_number",
        "model__model_number",
        "-model__model_number",
        "model__vendor__vendor_name",
        "-model__vendor__vendor_name",
        "depot",
        "-depot",
        "battery_type",
        "-battery_type",
        "battery_capacity",
        "-battery_capacity",
        "updated_date",
        "-updated_date",
    ]

    if sort_by not in valid_sorts:
        sort_by = "-updated_date"

    selected_project = (
        getattr(request, "project_code", None)
        or normalize_project_code(request.session.get("selected_project"))
        or get_default_project_code()
    )

    # Query vehicles with related data and filter by selected project name
    vehicles = (
        Vehicle.objects.select_related("model", "model__vendor")
        .prefetch_related("model__images")
        .filter(project_name__iexact=selected_project)
        .order_by(sort_by)
    )

    context = {
        "vehicles": vehicles,
        "current_sort": sort_by,
        "selected_project": selected_project,
    }

    return render(request, "dashboard/vehicle_master/vehicle_list.html", context)


@login_required
def vehicle_detail(request, registration_number):
    """Display detailed information for a single vehicle.

    Shows vehicle info, photos, specifications, vendor details, and related data.
    """
    vehicle = get_object_or_404(
        Vehicle.objects.select_related(
            "model", "model__vendor", "model__specification"
        ).prefetch_related("model__images"),
        registration_number=registration_number,
    )

    # Get vehicle type images
    images = vehicle.model.images.all() if vehicle.model else []

    # Get specification (OneToOne relationship)
    specification = None
    specs_dict = {}
    spec_sections = []
    flat_specs = []
    csv_specs = []

    if vehicle.model and hasattr(vehicle.model, "specification"):
        try:
            specification = vehicle.model.specification
            if specification and hasattr(specification, "specs"):
                raw_specs = specification.specs

                if isinstance(raw_specs, str):
                    try:
                        raw_specs = json.loads(raw_specs)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        raw_specs = {}

                if isinstance(raw_specs, dict):
                    specs_dict = _normalize_spec_value(raw_specs)

                    for key, value in specs_dict.items():
                        title = str(key).replace("_", " ").title()

                        if isinstance(value, (dict, list)):
                            section_items = []
                            for item_key, item_value in _flatten_spec_items(value):
                                section_items.append(
                                    {
                                        "label": str(item_key).replace("_", " ").title(),
                                        "value": item_value,
                                    }
                                )
                                csv_specs.append(
                                    {
                                        "key": f"{title} - {str(item_key).replace('_', ' ').title()}",
                                        "value": item_value,
                                    }
                                )

                            if section_items:
                                spec_sections.append(
                                    {"title": title, "items": section_items}
                                )
                        else:
                            display_value = str(value)
                            flat_specs.append(
                                {
                                    "key": title,
                                    "value": display_value,
                                }
                            )
                            csv_specs.append(
                                {
                                    "key": title,
                                    "value": display_value,
                                }
                            )
        except Exception:
            pass

    context = {
        "vehicle": vehicle,
        "images": images,
        "specification": specification,
        "specs_dict": specs_dict,
        "spec_sections": spec_sections,
        "flat_specs": flat_specs,
        "csv_specs": csv_specs,
    }

    return render(request, "dashboard/vehicle_master/vehicle_detail.html", context)
