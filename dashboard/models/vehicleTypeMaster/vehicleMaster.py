from django.db import models
from .vehicleType import ModelType


class Vehicle(models.Model):
    registration_number = models.CharField(max_length=50, unique=True)
    
    # Project and Company Information
    project_name = models.CharField(max_length=255, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    depot = models.CharField(max_length=255, blank=True, null=True)
    
    # Vehicle Identification
    chassis_number = models.CharField(max_length=100, blank=True, null=True)
    motor_no = models.CharField(max_length=100, blank=True, null=True)
    mac_id = models.CharField(max_length=100, blank=True, null=True)
    
    # Vehicle Details
    # ForeignKey to ModelType for accessing images, specs, and vendor info
    model = models.ForeignKey(
        ModelType, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="vehicles",
        help_text="Vehicle model type with specifications and images"
    )
    vehicle_type = models.CharField(max_length=100, blank=True, null=True)
    vehicle_category = models.CharField(max_length=50, blank=True, null=True)
    seating_capacity = models.IntegerField(blank=True, null=True)
    length = models.CharField(max_length=50, blank=True, null=True)
    vehicle_registration_date = models.DateField(blank=True, null=True)
    
    # Battery Information
    battery_type = models.CharField(max_length=255, blank=True, null=True)
    battery_capacity = models.CharField(max_length=50, blank=True, null=True)
    
    # Metadata
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.registration_number
