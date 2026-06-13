from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
import json


class DailyLog(models.Model):
    """
    Daily Log model for tracking vehicle operations and logistics.
    """
    # Primary Information
    log_date = models.DateField(verbose_name="Log Date", db_index=True)
    
    # Driver & Vehicle Information (Manawar to Jhulwania)
    driver_id = models.CharField(max_length=50, verbose_name="Driver ID", blank=True, null=True)
    lr = models.CharField(max_length=100, verbose_name="LR", blank=True, null=True, help_text="Lorry Receipt Number")
    from_location = models.CharField(max_length=255, verbose_name="From", blank=True, null=True)
    trailer_no = models.CharField(max_length=50, verbose_name="Trailer No.", blank=True, null=True)
    horse_no = models.CharField(max_length=50, verbose_name="Horse No.", blank=True, null=True)
    trailer_oem = models.CharField(max_length=100, verbose_name="Trailer OEM", blank=True, null=True)
    delivery_no = models.CharField(max_length=100, verbose_name="Delivery No.", blank=True, null=True)
    tonnage_load = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Tonnage Load", blank=True, null=True, help_text="in tonnes")
    toll_paid_manawar_jhulwania = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Toll Paid (Manawar to Jhulwania)", blank=True, null=True, help_text="in rupees")
    
    # Jhulwania Information
    driver_id_jhulwania = models.CharField(max_length=50, verbose_name="Driver ID (Jhulwania)", blank=True, null=True)
    trailer_no_jhulwania = models.CharField(max_length=50, verbose_name="Trailer No. (Jhulwania)", blank=True, null=True)
    horse_no_jhulwania = models.CharField(max_length=50, verbose_name="Horse No. (Jhulwania)", blank=True, null=True)
    toll_paid_jhulwania_dhule = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Toll Paid (Jhulwania to Dhule)", blank=True, null=True, help_text="in rupees")
    
    # Unload & Maintenance
    tonnage_unload = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Tonnage Unload", blank=True, null=True, help_text="in tonnes")
    maintenance = models.TextField(verbose_name="Maintenance", blank=True, null=True, help_text="Maintenance notes or issues")
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_logs', verbose_name="Created By")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    
    class Meta:
        db_table = 'mis_daily_log'
        verbose_name = 'Daily Log'
        verbose_name_plural = 'Daily Logs'
        ordering = ['-log_date', '-created_at']
        indexes = [
            models.Index(fields=['-log_date']),
            models.Index(fields=['horse_no']),
            models.Index(fields=['trailer_no']),
        ]
    
    def __str__(self):
        return f"Log {self.log_date} - {self.horse_no or 'N/A'} - {self.trailer_no or 'N/A'}"
    
    def clean(self):
        """Validate log data"""
        if self.tonnage_load and self.tonnage_unload:
            if self.tonnage_unload > self.tonnage_load:
                raise ValidationError({
                    'tonnage_unload': 'Tonnage unload cannot be greater than tonnage load'
                })


class CalculatedTrip(models.Model):
    """
    Stores calculated trip data from telemetry.
    Can be merged with DailyLog entries for complete reports.
    """
    # Identification
    vehicle_no = models.CharField(max_length=50, verbose_name="Vehicle Number", db_index=True)
    log_date = models.DateField(verbose_name="Trip Date", db_index=True)
    
    # Manawar (Start)
    manawar_in_time = models.DateTimeField(null=True, blank=True, verbose_name="Manawar In Time")
    manawar_out_time = models.DateTimeField(null=True, blank=True, verbose_name="Manawar Out Time")
    start_soc = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Start SOC (%)")
    trip_start_km = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Trip Start KM")
    closing_soc = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Closing SOC After Charging (%)")
    
    # Dhar/Manawar Charging
    dhar_charging_start_date = models.DateField(null=True, blank=True, verbose_name="Dhar Charging Start Date")
    dhar_charging_start_time = models.TimeField(null=True, blank=True, verbose_name="Dhar Charging Start Time")
    dhar_charging_end_time = models.TimeField(null=True, blank=True, verbose_name="Dhar Charging End Time")
    dhar_kwh = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="KWH (Dhar)")
    dhar_charging_duration = models.CharField(max_length=10, null=True, blank=True, verbose_name="Dhar Charging Time (HH:MM)")
    manawar_loading_time = models.CharField(max_length=10, null=True, blank=True, verbose_name="Manawar Loading Time (HH:MM)")
    
    # Manawar to Julwaniya
    manawar_julwaniya_stoppage = models.CharField(max_length=10, null=True, blank=True, verbose_name="Stoppage Manawar-Julwaniya (HH:MM)")
    manawar_julwaniya_moving = models.CharField(max_length=10, null=True, blank=True, verbose_name="Moving Time Manawar-Julwaniya (HH:MM)")
    manawar_julwaniya_total = models.CharField(max_length=10, null=True, blank=True, verbose_name="Total Time Manawar-Julwaniya (HH:MM)")
    
    # Julwaniya
    julwaniya_entry_time = models.DateTimeField(null=True, blank=True, verbose_name="Julwaniya Entry Time")
    julwaniya_exit_time = models.DateTimeField(null=True, blank=True, verbose_name="Julwaniya Exit Time")
    closing_km_julwaniya = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Closing KM Julwaniya")
    end_soc_julwaniya = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="End SOC Julwaniya (%)")
    start_soc_julwaniya = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Start SOC Julwaniya (%)")
    closing_soc_julwaniya = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Closing SOC Julwaniya (%)")
    julwaniya_charging_start_date = models.DateField(null=True, blank=True, verbose_name="Julwaniya Charging Start Date")
    julwaniya_charging_start_time = models.TimeField(null=True, blank=True, verbose_name="Julwaniya Charging Start Time")
    julwaniya_charging_end_time = models.TimeField(null=True, blank=True, verbose_name="Julwaniya Charging End Time")
    julwaniya_kwh = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="KWH Julwaniya")
    julwaniya_charging_duration = models.CharField(max_length=10, null=True, blank=True, verbose_name="Julwaniya Charging Time (HH:MM)")
    idle_time_julwaniya = models.CharField(max_length=10, null=True, blank=True, verbose_name="Idle Time Julwaniya (HH:MM)")
    start_km_after_julwaniya = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Start KM After Julwaniya")
    
    # Julwaniya to Dhule
    julwaniya_dhule_stoppage = models.CharField(max_length=10, null=True, blank=True, verbose_name="Stoppage Julwaniya-Dhule (HH:MM)")
    
    # Dhule
    dhule_entry_time = models.DateTimeField(null=True, blank=True, verbose_name="Dhule Entry Time")
    dhule_exit_time = models.DateTimeField(null=True, blank=True, verbose_name="Dhule Exit Time")
    closing_km_dhule = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Closing KM Dhule")
    end_soc_dhule = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="End SOC Dhule (%)")
    start_soc_dhule = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Start SOC Dhule (%)")
    closing_soc_dhule = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Closing SOC Dhule (%)")
    dhule_charging_start_date = models.DateField(null=True, blank=True, verbose_name="Dhule Charging Start Date")
    dhule_charging_start_time = models.TimeField(null=True, blank=True, verbose_name="Dhule Charging Start Time")
    dhule_charging_end_time = models.TimeField(null=True, blank=True, verbose_name="Dhule Charging End Time")
    dhule_kwh = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="KWH Dhule")
    dhule_charging_duration = models.CharField(max_length=10, null=True, blank=True, verbose_name="Dhule Charging Time (HH:MM)")
    idle_time_dhule = models.CharField(max_length=10, null=True, blank=True, verbose_name="Idle Time Dhule (HH:MM)")
    
    # Return Journey (Julwaniya-related fields removed)
    dhar_reach_time = models.DateTimeField(null=True, blank=True, verbose_name="Dhar Reach Time")
    trip_closed_km = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Trip Closed KM")
    dhar_reach_date = models.DateField(null=True, blank=True, verbose_name="Dhar Reach Date")
    vehicle_out_time = models.DateTimeField(null=True, blank=True, verbose_name="Vehicle Out Time")
    
    # Totals
    all_station_total_charging_hours = models.CharField(max_length=10, null=True, blank=True, verbose_name="Total Charging Hours (HH:MM)")
    vehicle_total_trip_time = models.CharField(max_length=10, null=True, blank=True, verbose_name="Total Trip Time (HH:MM)")
    total_distance_km = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Total Distance (km)")
    total_kwh = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Total KWH")
    efficiency_kwh_per_km = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Efficiency (kWh/km)")
    total_trip_km = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Total Trip KM")

    # Per-trip performance metrics (stored in seconds for aggregation)
    trip_duration_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Trip Duration (s)")
    plant_area_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Plant Area Time (s)")
    plant_area_stop_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Plant Area Stop Time (s)")
    plant_area_move_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Plant Area Move Time (s)")
    loading_stop_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Loading Stop Time (s)")
    unloading_stop_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Unloading Stop Time (s)")
    charging_area_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Charging Area Total Time (s)")
    plugged_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Plugged (Charging) Time (s)")
    charging_area_stop_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Charging Area Stop Time (s)")
    charging_area_move_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Charging Area Move Time (s)")
    unplanned_stoppage_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Unplanned Stoppage Time (s)")
    gained_soc = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name="Gained SOC (%)")
    
    # Plant-specific loading/unloading fields (calculated but not shown in exports)
    manawar_loading_entry_date = models.DateField(null=True, blank=True, verbose_name="Manawar Load Entry Date")
    manawar_loading_entry_time = models.TimeField(null=True, blank=True, verbose_name="Manawar Load Entry Time")
    manawar_loading_exit_time = models.TimeField(null=True, blank=True, verbose_name="Manawar Load Exit Time")
    extra_time_after_loading = models.CharField(max_length=10, null=True, blank=True, verbose_name="Extra Time After Loading (HH:MM)")
    dhule_unload_date = models.DateField(null=True, blank=True, verbose_name="Dhule Unload Date")  
    dhule_unload_entry_time = models.TimeField(null=True, blank=True, verbose_name="Dhule Unload Entry Time")
    dhule_unload_exit_date = models.DateField(null=True, blank=True, verbose_name="Dhule Unload Exit Date")
    dhule_unload_exit_time = models.TimeField(null=True, blank=True, verbose_name="Dhule Unload Exit Time")
    dhule_unload_time = models.CharField(max_length=10, null=True, blank=True, verbose_name="Dhule Unload Time (HH:MM)")
    dhule_plant_unload = models.CharField(max_length=10, null=True, blank=True, verbose_name="Dhule Plant Unload Time (HH:MM)")
    stoppage_d_j_m = models.CharField(max_length=10, null=True, blank=True, verbose_name="Stoppage D→J→M (HH:MM)")
    road_time_to_dhar = models.CharField(max_length=10, null=True, blank=True, verbose_name="Road Time to Dhar (HH:MM)")
    
    # Phase-specific delay metrics (in seconds) for trend graph optimization  
    manawar_loading_delay_s = models.IntegerField(null=True, blank=True, verbose_name="Manawar Loading Delay (s)", help_text="Delay beyond SLA for loading operations")
    dhule_unloading_delay_s = models.IntegerField(null=True, blank=True, verbose_name="Dhule Unloading Delay (s)", help_text="Delay beyond SLA for unloading operations")
    manawar_charging_delay_s = models.IntegerField(null=True, blank=True, verbose_name="Manawar Charging Delay (s)", help_text="Delay beyond SLA for charging")
    dhule_charging_delay_s = models.IntegerField(null=True, blank=True, verbose_name="Dhule Charging Delay (s)", help_text="Delay beyond SLA for charging") 
    jhulwania_charging_delay_s = models.IntegerField(null=True, blank=True, verbose_name="Jhulwania Charging Delay (s)", help_text="Delay beyond SLA for charging")
    maha_border_delay_s = models.IntegerField(null=True, blank=True, verbose_name="MH Border Delay (s)", help_text="Delay beyond SLA at border crossing")

    # Aggregate delay fields (sum of phase delays for fast trend calculation)
    total_delay_s = models.IntegerField(null=True, blank=True, verbose_name="Total Delay (s)", help_text="Sum of all phase delays beyond SLA")
    ultratech_delay_s = models.IntegerField(null=True, blank=True, verbose_name="Ultratech Delay (s)", help_text="Delay at Ultratech facilities (Manawar + Dhule)")
    driver_delay_s = models.IntegerField(null=True, blank=True, verbose_name="Driver/Transit Delay (s)", help_text="Delay during transit and other phases")

    # Transit duration metrics for comprehensive analytics
    manawar_to_jhulwania_duration_s = models.IntegerField(null=True, blank=True, verbose_name="Manawar→Jhulwania Duration (s)")
    jhulwania_to_dhule_duration_s = models.IntegerField(null=True, blank=True, verbose_name="Jhulwania→Dhule Duration (s)")  
    dhule_to_manawar_duration_s = models.IntegerField(null=True, blank=True, verbose_name="Dhule→Manawar Duration (s)")
    total_drive_time_s = models.IntegerField(null=True, blank=True, verbose_name="Total Drive Time (s)", help_text="Sum of all transit phases")
    
    # Metadata
    calculated_at = models.DateTimeField(auto_now_add=True, verbose_name="Calculated At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    
    # Store raw calculation data as JSON for debugging
    raw_data = models.TextField(null=True, blank=True, verbose_name="Raw Calculation Data")
    
    class Meta:
        db_table = 'mis_calculated_trip'
        verbose_name = 'Calculated Trip'
        verbose_name_plural = 'Calculated Trips'
        ordering = ['-log_date', '-manawar_in_time']
        indexes = [
            models.Index(fields=['-log_date']),
            models.Index(fields=['vehicle_no']),
            models.Index(fields=['vehicle_no', 'log_date']),
            # Performance indexes for fast trend queries
            models.Index(fields=['log_date', 'total_delay_s'], name='mis_calc_trip_date_delay_idx'),
            models.Index(fields=['log_date', 'vehicle_no'], name='mis_calc_trip_date_vehicle_idx'),
        ]
        unique_together = [['vehicle_no', 'manawar_in_time']]
    
    def __str__(self):
        return f"Trip {self.vehicle_no} - {self.log_date}"
    
    def set_raw_data(self, data_dict):
        """Store raw calculation data as JSON."""
        self.raw_data = json.dumps(data_dict, default=str)
    
    def get_raw_data(self):
        """Retrieve raw calculation data from JSON."""
        if self.raw_data:
            return json.loads(self.raw_data)
        return {}


class VehicleTripState(models.Model):
    """
    Stores the carry-over state for a vehicle's in-progress trip.

    Used by IncrementalTripOrchestrator to avoid re-fetching large date ranges.
    After processing each day, the raw telemetry rows for the current unfinished
    trip (from the last Manawar entry onwards) are stored here so the next day's
    fetch can seamlessly continue trip calculation.
    """
    vehicle_no = models.CharField(max_length=50, db_index=True, verbose_name="Vehicle Number")
    state_date = models.DateField(db_index=True, verbose_name="State As-Of Date")

    # Raw telemetry rows (JSON array) for the current in-progress trip.
    # Trimmed to rows >= last Manawar entry to keep size bounded.
    accumulated_rows_json = models.TextField(default="[]", verbose_name="Accumulated Rows (JSON)")

    # Summary fields for quick inspection / debugging
    last_cluster = models.CharField(max_length=50, blank=True, null=True, verbose_name="Last Known Cluster")
    last_ts = models.DateTimeField(null=True, blank=True, verbose_name="Last Telemetry Timestamp")
    rows_count = models.IntegerField(default=0, verbose_name="Accumulated Row Count")

    class Meta:
        db_table = "mis_vehicle_trip_state"
        verbose_name = "Vehicle Trip State"
        verbose_name_plural = "Vehicle Trip States"
        unique_together = [["vehicle_no", "state_date"]]
        indexes = [
            models.Index(fields=["vehicle_no", "-state_date"]),
        ]
        ordering = ["-state_date"]

    def __str__(self):
        return f"State {self.vehicle_no} @ {self.state_date} ({self.rows_count} rows, last: {self.last_cluster})"


class RecomputeRun(models.Model):
    """Tracks month-to-date recompute executions for observability and audit."""
    STATUS_CHOICES = (
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
    )

    month = models.DateField(help_text="First day of the month being recomputed")
    target_day = models.DateField(help_text="Target day (typically yesterday)")
    lookback_days = models.IntegerField(default=5)
    vehicle_no = models.CharField(max_length=50, blank=True, null=True, help_text="Optional vehicle filter")

    # Metrics
    raw_rows = models.IntegerField(default=0)
    telemetry_rows = models.IntegerField(default=0)
    calculated_trips = models.IntegerField(default=0)
    deleted_count = models.IntegerField(default=0)
    saved_count = models.IntegerField(default=0)
    duration_seconds = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="running")
    error_message = models.TextField(blank=True, null=True)

    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'mis_recompute_run'
        indexes = [
            models.Index(fields=['-started_at']),
            models.Index(fields=['month']),
            models.Index(fields=['status']),
        ]
        ordering = ['-started_at']

    def __str__(self):
        m = self.month.strftime('%Y-%m') if self.month else 'N/A'
        return f"Recompute {m} ({self.status})"


class FullPipelineRun(models.Model):
    """
    Audit log for a full backfill/pipeline run that calculates trips
    AND builds TripPerformanceSummary for a date range.
    """
    STATUS_CHOICES = (
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
    )

    start_date = models.DateField(verbose_name="Range Start Date")
    end_date = models.DateField(verbose_name="Range End Date")
    vehicle_no = models.CharField(max_length=50, blank=True, null=True, verbose_name="Vehicle Filter")

    # Trip calculation metrics
    trips_calculated = models.IntegerField(default=0, verbose_name="Trips Calculated")
    trips_saved = models.IntegerField(default=0, verbose_name="Trips Saved to DB")

    # Summary metrics
    summary_months_updated = models.IntegerField(default=0, verbose_name="Summary Months Updated")
    summary_vehicles_updated = models.IntegerField(default=0, verbose_name="Summary Vehicles Updated")

    # Timing
    duration_seconds = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Duration (s)")
    started_at = models.DateTimeField(auto_now_add=True, verbose_name="Started At")
    ended_at = models.DateTimeField(null=True, blank=True, verbose_name="Ended At")

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="running", verbose_name="Status")
    error_message = models.TextField(blank=True, null=True, verbose_name="Error Message")
    log = models.TextField(blank=True, null=True, verbose_name="Run Log")

    class Meta:
        db_table = 'mis_full_pipeline_run'
        verbose_name = 'Full Pipeline Run'
        verbose_name_plural = 'Full Pipeline Runs'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['-started_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Pipeline {self.start_date} → {self.end_date} ({self.status})"

    def append_log(self, msg: str):
        from django.utils import timezone
        ts = timezone.now().strftime('%H:%M:%S')
        line = f"[{ts}] {msg}"
        self.log = (self.log or "") + line + "\n"


class TripPerformanceSummary(models.Model):
    """
    Monthly aggregated trip performance per vehicle.
    Populated by the build_performance_summary management command.
    All duration fields are stored in seconds for arithmetic simplicity.
    """
    month = models.CharField(max_length=7, db_index=True, verbose_name="Month (YYYY-MM)")
    vehicle_no = models.CharField(max_length=50, db_index=True, verbose_name="Vehicle Number")

    trip_count = models.IntegerField(default=0, verbose_name="Trip Count")
    avg_trip_duration_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Trip Duration (s)")
    avg_efficiency_kwh_per_km = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, verbose_name="Avg Efficiency (kWh/km)")
    avg_plant_area_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Plant Area Time (s)")
    avg_plant_area_stop_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Plant Area Stop Time (s)")
    avg_plant_area_move_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Plant Area Move Time (s)")
    avg_loading_stop_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Loading Stop Time (s)")
    avg_unloading_stop_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Unloading Stop Time (s)")
    avg_charging_area_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Charging Area Time (s)")
    avg_plugged_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Plugged Time (s)")
    avg_charging_area_stop_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Charging Area Stop Time (s)")
    avg_charging_area_move_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Charging Area Move Time (s)")
    avg_unplanned_stoppage_time_s = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True, verbose_name="Avg Unplanned Stoppage Time (s)")
    avg_gained_soc = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name="Avg Gained SOC (%)")

    computed_at = models.DateTimeField(auto_now=True, verbose_name="Last Computed At")

    class Meta:
        db_table = 'mis_trip_performance_summary'
        verbose_name = 'Trip Performance Summary'
        verbose_name_plural = 'Trip Performance Summaries'
        unique_together = [['month', 'vehicle_no']]
        indexes = [
            models.Index(fields=['month', 'vehicle_no']),
        ]
        ordering = ['month', 'vehicle_no']

    def __str__(self):
        return f"Performance {self.month} - {self.vehicle_no} ({self.trip_count} trips)"
