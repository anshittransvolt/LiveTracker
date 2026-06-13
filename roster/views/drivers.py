from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q
from django.contrib import messages
from django.core.exceptions import ValidationError
from ..models import DriverMaster
import re
from django.views.decorators.cache import cache_page
from django.contrib.auth.decorators import login_required


@login_required
def driver_master_page(request):
    if request.method == "POST":
        try:
            employee_code = request.POST.get("employee_code", "").strip()
            employee_name = request.POST.get("employee_name", "").strip()
            phone = request.POST.get("phone", "").strip()
            ultratech_id = request.POST.get("ultratech_id", "").strip()

            if not employee_code or not employee_name:
                messages.error(request, "Employee code and name are required.")
                return redirect("roster:driver_master_page")

            # Validate phone if provided
            if phone:
                phone_digits = re.sub(r"\D", "", phone)
                if len(phone_digits) != 10:
                    messages.error(request, "Phone number must be exactly 10 digits.")
                    return redirect("roster:driver_master_page")

            driver = DriverMaster(
                employee_code=employee_code,
                employee_name=employee_name,
                phone=phone if phone else None,
                ultratech_id=ultratech_id if ultratech_id else None,
            )
            driver.full_clean()
            driver.save()

            messages.success(request, f"Driver {employee_name} added successfully!")
            return redirect("roster:driver_master_page")
        except ValidationError as e:
            error_message = " ".join(
                [
                    f"{field}: {', '.join(errors)}"
                    for field, errors in e.message_dict.items()
                ]
            )
            messages.error(request, f"Validation Error: {error_message}")
            return redirect("roster:driver_master_page")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect("roster:driver_master_page")

    # Get search query
    search_query = request.GET.get("search", "").strip()

    drivers = DriverMaster.objects.all().order_by("-is_active", "employee_code")

    # Apply search filter
    if search_query:
        drivers = drivers.filter(
            Q(employee_code__icontains=search_query)
            | Q(employee_name__icontains=search_query)
            | Q(ultratech_id__icontains=search_query)
        )

    return render(
        request,
        "driver_master.html",
        {"drivers": drivers, "search_query": search_query},
    )


def driver_edit(request, driver_id):
    driver = get_object_or_404(DriverMaster, pk=driver_id)

    if request.method == "POST":
        try:
            employee_name = request.POST.get("employee_name", "").strip()
            phone = request.POST.get("phone", "").strip()
            ultratech_id = request.POST.get("ultratech_id", "").strip()

            if not employee_name:
                messages.error(request, "Employee name is required.")
                return redirect("roster:driver_edit", driver_id=driver_id)

            # Validate phone if provided
            if phone:
                phone_digits = re.sub(r"\D", "", phone)
                if len(phone_digits) != 10:
                    messages.error(request, "Phone number must be exactly 10 digits.")
                    return redirect("roster:driver_edit", driver_id=driver_id)

            driver.employee_name = employee_name
            driver.phone = phone if phone else None
            driver.ultratech_id = ultratech_id if ultratech_id else None
            driver.full_clean()
            driver.save()

            messages.success(request, f"Driver {employee_name} updated successfully!")
            return redirect("roster:driver_master_page")
        except ValidationError as e:
            error_message = " ".join(
                [
                    f"{field}: {', '.join(errors)}"
                    for field, errors in e.message_dict.items()
                ]
            )
            messages.error(request, f"Validation Error: {error_message}")
            return redirect("roster:driver_edit", driver_id=driver_id)
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect("roster:driver_edit", driver_id=driver_id)

    return render(request, "driver_edit.html", {"driver": driver})


def driver_toggle_active(request, driver_id):
    driver = get_object_or_404(DriverMaster, pk=driver_id)
    driver.is_active = not driver.is_active
    driver.save(update_fields=["is_active"])

    status = "activated" if driver.is_active else "deactivated"
    messages.success(request, f"Driver {driver.employee_name} has been {status}.")
    return redirect("roster:driver_master_page")
