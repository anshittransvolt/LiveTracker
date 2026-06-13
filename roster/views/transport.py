from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q
from django.contrib import messages
from django.core.exceptions import ValidationError
from ..models import TransportMaster
import re
from django.views.decorators.cache import cache_page
from django.contrib.auth.decorators import login_required


@login_required
def transport_master_page(request):
    if request.method == "POST":
        try:
            horse_chassis_no = request.POST.get("horse_chassis_no", "").strip()
            horse_number = request.POST.get("horse_number", "").strip()
            trolley_number = request.POST.get("trolley_number", "").strip()
            trolley_chassis_no = request.POST.get("trolley_chassis_no", "").strip()

            if not horse_chassis_no or not horse_number:
                messages.error(
                    request, "Horse chassis number and horse number are required."
                )
                return redirect("roster:transport_master_page")

            transport = TransportMaster(
                horse_chassis_no=horse_chassis_no,
                horse_number=horse_number,
                trolley_number=trolley_number if trolley_number else None,
                trolley_chassis_no=trolley_chassis_no if trolley_chassis_no else None,
            )
            transport.full_clean()
            transport.save()

            messages.success(request, f"Transport {horse_number} added successfully!")
            return redirect("roster:transport_master_page")
        except ValidationError as e:
            error_message = " ".join(
                [
                    f"{field}: {', '.join(errors)}"
                    for field, errors in e.message_dict.items()
                ]
            )
            messages.error(request, f"Validation Error: {error_message}")
            return redirect("roster:transport_master_page")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect("roster:transport_master_page")

    transports = TransportMaster.objects.all()
    return render(request, "transport_master.html", {"transports": transports})
