from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import json
import logging

# from ..models import transport_model as TransportMaster, driver_model as DriverMaster, assignment_models as HorseTrolleyAssignment
from ..models import TransportMaster, DriverMaster, HorseTrolleyAssignment, AssignmentLog
from django.contrib.auth.decorators import login_required
import re

logger = logging.getLogger(__name__)


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
        performed_by=user if user and user.is_authenticated else None,
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
def autocomplete_horse(request):
    query = request.GET.get("q", "")
    if len(query) >= 2:
        horses = TransportMaster.objects.filter(horse_number__icontains=query).values(
            "horse_number"
        )[:10]
        return JsonResponse(list(horses), safe=False)
    return JsonResponse([], safe=False)


@login_required
def autocomplete_trolley(request):
    query = request.GET.get("q", "")
    if len(query) >= 2:
        trolleys = (
            TransportMaster.objects.filter(trolley_number__icontains=query)
            .exclude(trolley_number__isnull=True)
            .values("trolley_number")[:10]
        )
        return JsonResponse(list(trolleys), safe=False)
    return JsonResponse([], safe=False)


@login_required
def autocomplete_driver(request):
    query = request.GET.get("q", "")
    if len(query) >= 2:
        drivers = DriverMaster.objects.filter(
            Q(employee_code__icontains=query) | Q(employee_name__icontains=query),
            is_active=True,
        )[:10]

        results = [
            {
                "employee_code": driver.employee_code,
                "employee_name": driver.employee_name,
            }
            for driver in drivers
        ]

        return JsonResponse(results, safe=False)
    return JsonResponse([], safe=False)


@login_required
@require_http_methods(["GET"])
def get_drivers_api(request):
    """
    API endpoint to get list of all drivers.
    Returns driver details for dropdown population.
    
    Usage: GET /roster/api/drivers/
    """
    try:
        drivers = DriverMaster.objects.all().order_by('employee_name')
        
        driver_list = []
        for driver in drivers:
            driver_list.append({
                'employee_code': driver.employee_code,
                'employee_name': driver.employee_name,
                'phone': driver.phone if driver.phone else None,
                'is_active': driver.is_active
            })
        
        return JsonResponse({
            'success': True,
            'drivers': driver_list,
            'count': len(driver_list)
        })
    except Exception as e:
        logger.error(f"Error fetching drivers: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def check_assignments_api(request):
    """
    API endpoint to check for existing assignments for a vehicle and/or driver.
    Returns information about current assignments.
    
    Usage: GET /roster/api/assignments/?vehicle=MH12AB1234&driver=DRV001
    """
    try:
        vehicle_number = request.GET.get('vehicle')
        driver_code = request.GET.get('driver')
        
        result = {
            'success': True,
            'vehicle_assignment': None,
            'driver_assignment': None
        }
        
        # Check if vehicle has an assignment
        if vehicle_number:
            try:
                vehicle_assignment = HorseTrolleyAssignment.objects.select_related('horse', 'driver').get(
                    horse__horse_number=vehicle_number
                )
                result['vehicle_assignment'] = {
                    'horse_number': vehicle_assignment.horse.horse_number,
                    'driver_code': vehicle_assignment.driver.employee_code,
                    'driver_name': vehicle_assignment.driver.employee_name,
                    'route': vehicle_assignment.route,
                    'place': vehicle_assignment.place,
                    'tonnage': vehicle_assignment.tonnage,
                    'assigned_date': vehicle_assignment.assigned_date.strftime('%Y-%m-%d') if vehicle_assignment.assigned_date else None
                }
            except HorseTrolleyAssignment.DoesNotExist:
                pass
        
        # Check if driver has an assignment
        if driver_code:
            try:
                driver_assignment = HorseTrolleyAssignment.objects.select_related('horse', 'driver').get(
                    driver__employee_code=driver_code
                )
                result['driver_assignment'] = {
                    'horse_number': driver_assignment.horse.horse_number,
                    'driver_code': driver_assignment.driver.employee_code,
                    'driver_name': driver_assignment.driver.employee_name,
                    'route': driver_assignment.route,
                    'place': driver_assignment.place,
                    'tonnage': driver_assignment.tonnage,
                    'assigned_date': driver_assignment.assigned_date.strftime('%Y-%m-%d') if driver_assignment.assigned_date else None
                }
            except HorseTrolleyAssignment.DoesNotExist:
                pass
        
        return JsonResponse(result)
        
    except Exception as e:
        logger.error(f"Error checking assignments: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def assign_driver_api(request):
    """
    API endpoint to assign or update driver for a vehicle.
    Creates or updates HorseTrolleyAssignment record.
    
    Usage: POST /roster/api/assign-driver/
    Body: {"horse_number": "MH12AB1234", "driver_code": "DRV001", "route": "DHAR_TO_DHULE", "place": "DHAR", "tonnage": "25T"}
    """
    try:
        data = json.loads(request.body)
        horse_number = data.get('horse_number')
        driver_code = data.get('driver_code')
        route = data.get('route')
        place = data.get('place')
        tonnage = data.get('tonnage')
        
        if not horse_number or not driver_code:
            return JsonResponse({
                'success': False,
                'message': 'Missing horse_number or driver_code'
            }, status=400)
        
        # Validate that horse exists
        try:
            horse = TransportMaster.objects.get(horse_number=horse_number)
        except TransportMaster.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': f'Vehicle {horse_number} not found in transport master'
            }, status=404)
        
        # Validate that driver exists and is active
        try:
            driver = DriverMaster.objects.get(employee_code=driver_code)
            if not driver.is_active:
                return JsonResponse({
                    'success': False,
                    'message': f'Driver {driver.employee_name} is not active'
                }, status=400)
        except DriverMaster.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': f'Driver {driver_code} not found'
            }, status=404)
        
        # Check if driver is already assigned to a different vehicle
        existing_driver_assignment = HorseTrolleyAssignment.objects.filter(
            driver=driver
        ).exclude(horse=horse).first()
        
        # Store info for logging
        previous_driver_for_truck = None
        previous_truck_for_driver = None
        
        # Create or update assignment using update_or_create (unique constraint on horse)
        with transaction.atomic():
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
            
            # Prepare update defaults
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
                
                # Always preserve existing LR number when updating
                update_defaults['lr_number'] = existing_truck_assignment.lr_number
            else:
                # CREATING: Use provided values or None
                update_defaults['route'] = route
                update_defaults['place'] = place
                update_defaults['tonnage'] = tonnage
                update_defaults['lr_number'] = None  # LR number is set separately in web form only
            
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
                notes=f"Assignment {'created' if created else 'updated'} via API" + 
                      (f" (driver reassigned from {previous_truck_for_driver})" if previous_truck_for_driver else "")
            )
        
        action = 'assigned' if created else 'updated'
        
        return JsonResponse({
            'success': True,
            'message': f'Driver {driver.employee_name} successfully {action} to vehicle {horse_number}',
            'assignment': {
                'horse_number': horse_number,
                'driver_code': driver.employee_code,
                'driver_name': driver.employee_name,
                'driver_phone': driver.phone if driver.phone else 'N/A',
                'route': assignment.route,
                'place': assignment.place,
                'tonnage': assignment.tonnage,
                'assigned_date': assignment.assigned_date.strftime('%Y-%m-%d %H:%M:%S') if assignment.assigned_date else None
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error assigning driver: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def unassign_driver_api(request):
    """
    API endpoint to unassign driver from a vehicle.
    Removes HorseTrolleyAssignment record.
    
    Usage: POST /roster/api/unassign-driver/
    Body: {"horse_number": "MH12AB1234"}
    """
    try:
        data = json.loads(request.body)
        horse_number = data.get('horse_number')
        
        if not horse_number:
            return JsonResponse({
                'success': False,
                'message': 'Missing horse_number'
            }, status=400)
        
        # Find and delete the assignment
        try:
            assignment = HorseTrolleyAssignment.objects.get(horse__horse_number=horse_number)
            driver_name = assignment.driver.employee_name if assignment.driver else 'Unknown'
            driver = assignment.driver
            
            with transaction.atomic():
                # Log deletion before deleting
                ip_address = get_client_ip(request)
                log_assignment_action(
                    action='DELETE',
                    horse_number=horse_number,
                    driver=driver,
                    user=request.user,
                    ip_address=ip_address,
                    notes=f"Assignment deleted via API"
                )
                
                assignment.delete()
                
                # Clear driver cache for this vehicle
                from roster.services.driverService import clear_driver_cache
                clear_driver_cache(horse_number)
            
            return JsonResponse({
                'success': True,
                'message': f'Driver {driver_name} successfully unassigned from vehicle {horse_number}'
            })
            
        except HorseTrolleyAssignment.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': f'No driver assignment found for vehicle {horse_number}'
            }, status=404)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error unassigning driver: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_driver_by_vehicle_api(request, registration_number):
    """
    API endpoint to get driver details for a specific vehicle.
    Uses the driverService for optimized caching.
    
    Args:
        registration_number: Vehicle registration number
    
    Returns:
        JSON with driver information
    """
    try:
        from roster.services.driverService import get_driver_by_vehicle
        
        driver_info = get_driver_by_vehicle(registration_number)
        
        return JsonResponse({
            'success': True,
            'driver_name': driver_info['driver_name'],
            'driver_phone': driver_info['driver_phone'],
            'driver_code': driver_info['driver_code'],
            'has_driver': driver_info['has_driver']
        })
        
    except Exception as e:
        logger.error(f"Error fetching driver for vehicle {registration_number}: {str(e)}")
        return JsonResponse({
            'success': False,
            'driver_name': 'Error',
            'driver_phone': 'N/A',
            'driver_code': None,
            'has_driver': False,
            'error': str(e)
        }, status=500)
