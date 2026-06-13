from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q
from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.contrib.auth.decorators import login_required, user_passes_test
from ..models import TransportMaster, DriverMaster, HorseTrolleyAssignment, AssignmentLog
from django.views.decorators.cache import cache_page
import re


@login_required
def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def log_assignment_action(action, horse_number, driver, user, ip_address, previous_driver=None, notes=None, route=None, place=None, lr_number=None, tonnage=None, previous_route=None, previous_place=None, previous_lr_number=None, previous_tonnage=None):
    """Helper function to log assignment actions"""
    log_entry = AssignmentLog(
        horse_number=horse_number,
        driver_code=driver.employee_code,
        driver_name=driver.employee_name,
        route=route,
        place=place,
        lr_number=lr_number,
        tonnage=tonnage,
        action=action,
        performed_by=user if user.is_authenticated else None,
        ip_address=ip_address,
        notes=notes
    )
    
    if previous_driver:
        log_entry.previous_driver_code = previous_driver.employee_code
        log_entry.previous_driver_name = previous_driver.employee_name
    
    # Store previous values for UPDATE actions
    if action == 'UPDATE':
        log_entry.previous_route = previous_route
        log_entry.previous_place = previous_place
        log_entry.previous_lr_number = previous_lr_number
        log_entry.previous_tonnage = previous_tonnage
    
    log_entry.save()
    return log_entry


@login_required
def assignment_page(request):
    if request.method == "POST":
        try:
            horse_number = request.POST.get("horse_number", "").strip()
            driver_code = request.POST.get("driver_code", "").strip()
            route = request.POST.get("route", "").strip() or None
            place = request.POST.get("place", "").strip() or None
            lr_number = request.POST.get("lr_number", "").strip() or None
            tonnage = request.POST.get("tonnage", "").strip() or None
            
            # Only allow lr_number if place is DHAR
            if place != 'DHAR':
                lr_number = None

            if not horse_number or not driver_code:
                messages.error(request, "Please fill all required fields.")
                return redirect("roster:assignment_page")

            # Get the horse and driver objects
            try:
                horse = TransportMaster.objects.get(horse_number=horse_number)
            except TransportMaster.DoesNotExist:
                messages.error(request, f"Horse number '{horse_number}' not found in Transport Master.")
                return redirect("roster:assignment_page")

            try:
                driver = DriverMaster.objects.get(employee_code=driver_code)
            except DriverMaster.DoesNotExist:
                messages.error(request, f"Driver code '{driver_code}' not found in Driver Master.")
                return redirect("roster:assignment_page")

            # Check if driver is already assigned to a different vehicle
            existing_driver_assignment = HorseTrolleyAssignment.objects.filter(
                driver=driver
            ).exclude(horse=horse).first()
            
            # Store info for logging
            previous_driver_for_truck = None
            previous_truck_for_driver = None
            
            # Get existing assignment for this truck to check for updates
            existing_truck_assignment = HorseTrolleyAssignment.objects.filter(horse=horse).first()
            previous_driver_for_truck = existing_truck_assignment.driver if existing_truck_assignment else None
            
            # If driver is assigned to another truck, remove that assignment first
            if existing_driver_assignment:
                previous_truck_for_driver = existing_driver_assignment.horse_number
                
                # Log the removal of driver from previous truck
                log_assignment_action(
                    action='UPDATE',
                    horse_number=existing_driver_assignment.horse_number,
                    driver=driver,
                    user=request.user,
                    ip_address=get_client_ip(request),
                    notes=f"Driver reassigned from {existing_driver_assignment.horse_number} to {horse_number}"
                )
                
                existing_driver_assignment.delete()
                
                # Clear cache for previous truck
                from roster.services.driverService import clear_driver_cache
                clear_driver_cache(existing_driver_assignment.horse_number)
            
            # Prepare defaults for update_or_create
            from django.utils import timezone
            update_defaults = {
                'driver': driver,
                'assigned_date': timezone.now(),  # Always update timestamp
            }
            
            # Handle updating vs creating
            if existing_truck_assignment:
                # UPDATING: Only update fields that are provided, preserve others
                if route is not None:
                    update_defaults['route'] = route
                else:
                    update_defaults['route'] = existing_truck_assignment.route
                
                if place is not None:
                    update_defaults['place'] = place
                else:
                    update_defaults['place'] = existing_truck_assignment.place
                
                if tonnage is not None:
                    update_defaults['tonnage'] = tonnage
                else:
                    update_defaults['tonnage'] = existing_truck_assignment.tonnage
                
                # Update LR number if provided and place is DHAR, otherwise preserve existing
                if lr_number and place == 'DHAR':
                    update_defaults['lr_number'] = lr_number
                else:
                    update_defaults['lr_number'] = existing_truck_assignment.lr_number
            else:
                # CREATING: Use provided values or None
                update_defaults['route'] = route
                update_defaults['place'] = place
                update_defaults['tonnage'] = tonnage
                # Set LR number only if place is DHAR
                update_defaults['lr_number'] = lr_number if place == 'DHAR' else None
            
            # Create or update assignment using ForeignKey relationships
            assignment, created = HorseTrolleyAssignment.objects.update_or_create(
                horse=horse,
                defaults=update_defaults
            )
            
            # Clear driver cache for this vehicle
            from roster.services.driverService import clear_driver_cache
            clear_driver_cache(horse_number)
            
            # Log the action
            ip_address = get_client_ip(request)
            action = 'CREATE' if created else 'UPDATE'
            
            log_assignment_action(
                action=action,
                horse_number=horse_number,
                driver=driver,
                user=request.user,
                ip_address=ip_address,
                previous_driver=previous_driver_for_truck if not created and previous_driver_for_truck != driver else None,
                route=assignment.route,
                place=assignment.place,
                lr_number=assignment.lr_number,
                tonnage=assignment.tonnage,
                previous_route=existing_truck_assignment.route if existing_truck_assignment and not created else None,
                previous_place=existing_truck_assignment.place if existing_truck_assignment and not created else None,
                previous_lr_number=existing_truck_assignment.lr_number if existing_truck_assignment and not created else None,
                previous_tonnage=existing_truck_assignment.tonnage if existing_truck_assignment and not created else None,
                notes=f"Assignment {'created' if created else 'updated'} via web form" +
                      (f" (driver reassigned from {previous_truck_for_driver})" if previous_truck_for_driver else "")
            )
            
            action_text = "created" if created else "updated"
            messages.success(request, f"Assignment {action_text} successfully!")
            return redirect("roster:assignment_page")
        except ValidationError as e:
            error_message = " ".join(
                [
                    f"{field}: {', '.join(errors)}"
                    for field, errors in e.message_dict.items()
                ]
            )
            messages.error(request, f"Validation Error: {error_message}")
            return redirect("roster:assignment_page")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect("roster:assignment_page")

    # Get search query
    search_query = request.GET.get("search", "").strip()

    # Use select_related to optimize queries
    assignments = HorseTrolleyAssignment.objects.select_related('horse', 'driver').all()

    # Apply search filter if query exists
    if search_query:
        assignments = assignments.filter(
            Q(horse__horse_number__icontains=search_query)
            | Q(driver__employee_code__icontains=search_query)
            | Q(driver__employee_name__icontains=search_query)
        )[:50]
    else:
        assignments = assignments[:50]

    return render(
        request,
        "assignment.html",
        {"assignments": assignments, "search_query": search_query},
    )


@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser, login_url='/admin/login/')
def assignment_logs_page(request):
    """
    Display assignment logs with filtering and search.
    Shows who created/updated/deleted assignments and when.
    Only accessible to admin/staff users.
    """
    # Get filters
    action_filter = request.GET.get('action', '')
    search_query = request.GET.get('search', '').strip()
    
    # Base query
    logs = AssignmentLog.objects.select_related('performed_by').all()
    
    # Apply action filter
    if action_filter:
        logs = logs.filter(action=action_filter)
    
    # Apply search filter
    if search_query:
        logs = logs.filter(
            Q(horse_number__icontains=search_query) |
            Q(driver_name__icontains=search_query) |
            Q(driver_code__icontains=search_query) |
            Q(performed_by__username__icontains=search_query)
        )
    
    # Limit results
    logs = logs[:100]
    
    return render(
        request,
        "assignment_logs.html",
        {
            "logs": logs,
            "search_query": search_query,
            "action_filter": action_filter,
        },
    )
