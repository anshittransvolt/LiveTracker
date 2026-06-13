from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from .models import DailyLog, CalculatedTrip, VehicleTripState
from .models import RecomputeRun, TripPerformanceSummary, FullPipelineRun


class DailyLogResource(resources.ModelResource):
    class Meta:
        model = DailyLog
        import_id_fields = ['id']
        fields = (
            'id', 'log_date', 'driver_id', 'lr', 'from_location', 'trailer_no', 'horse_no',
            'trailer_oem', 'delivery_no', 'tonnage_load', 'toll_paid_manawar_jhulwania',
            'driver_id_jhulwania', 'trailer_no_jhulwania', 'horse_no_jhulwania',
            'toll_paid_jhulwania_dhule', 'tonnage_unload', 'maintenance', 'created_by', 'created_at', 'updated_at'
        )
        export_order = fields


@admin.register(DailyLog)
class DailyLogAdmin(ImportExportModelAdmin):
    resource_class = DailyLogResource
    
    list_display = (
        'log_date', 'horse_no', 'trailer_no', 'driver_id', 'from_location',
        'tonnage_load', 'tonnage_unload', 'created_by', 'created_at'
    )
    
    list_filter = ('log_date', 'from_location', 'trailer_oem', 'created_at')
    
    search_fields = (
        'horse_no', 'trailer_no', 'driver_id', 'lr', 'delivery_no',
        'driver_id_jhulwania', 'trailer_no_jhulwania', 'horse_no_jhulwania'
    )
    
    date_hierarchy = 'log_date'
    
    readonly_fields = ('created_at', 'updated_at', 'created_by')
    
    fieldsets = (
        ('Log Information', {
            'fields': ('log_date',)
        }),
        ('Manawar to Jhulwania', {
            'fields': (
                'driver_id', 'lr', 'from_location', 'trailer_no', 'horse_no',
                'trailer_oem', 'delivery_no', 'tonnage_load', 'toll_paid_manawar_jhulwania'
            )
        }),
        ('Jhulwania Details', {
            'fields': (
                'driver_id_jhulwania', 'trailer_no_jhulwania', 'horse_no_jhulwania',
                'toll_paid_jhulwania_dhule'
            )
        }),
        ('Unload & Maintenance', {
            'fields': ('tonnage_unload', 'maintenance')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # If creating new object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(RecomputeRun)
class RecomputeRunAdmin(admin.ModelAdmin):
    list_display = (
        'started_at', 'month', 'target_day', 'status', 'lookback_days',
        'deleted_count', 'saved_count', 'calculated_trips', 'raw_rows', 'telemetry_rows', 'duration_seconds'
    )
    list_filter = ('status', 'month',)
    search_fields = ('vehicle_no', 'error_message')
    readonly_fields = ('started_at', 'ended_at')

@admin.register(CalculatedTrip)
class CalculatedTripAdmin(admin.ModelAdmin):
    list_display = (
        'vehicle_no', 'log_date', 'manawar_in_time', 'dhar_reach_time',
        'total_distance_km', 'total_kwh', 'vehicle_total_trip_time', 'calculated_at'
    )
    
    list_filter = ('log_date', 'vehicle_no', 'calculated_at')
    
    search_fields = ('vehicle_no',)
    
    readonly_fields = ('calculated_at', 'updated_at', 'raw_data')
    
    date_hierarchy = 'log_date'
    
    fieldsets = (
        ('Trip Identification', {
            'fields': ('vehicle_no', 'log_date', 'calculated_at', 'updated_at')
        }),
        ('Manawar (Start)', {
            'fields': (
                'manawar_in_time', 'manawar_out_time', 'start_soc', 'trip_start_km', 'closing_soc',
                'dhar_charging_start_date', 'dhar_charging_start_time', 'dhar_charging_end_time',
                'dhar_kwh', 'dhar_charging_duration', 'manawar_loading_time'
            )
        }),
        ('Julwaniya', {
            'fields': (
                'julwaniya_entry_time', 'julwaniya_exit_time', 'closing_km_julwaniya',
                'end_soc_julwaniya', 'start_soc_julwaniya', 'closing_soc_julwaniya',
                'julwaniya_charging_start_date', 'julwaniya_charging_start_time',
                'julwaniya_charging_end_time', 'julwaniya_kwh', 'julwaniya_charging_duration',
                'idle_time_julwaniya', 'start_km_after_julwaniya'
            )
        }),
        ('Dhule', {
            'fields': (
                'dhule_entry_time', 'dhule_exit_time', 'closing_km_dhule',
                'end_soc_dhule', 'start_soc_dhule', 'closing_soc_dhule',
                'dhule_charging_start_date', 'dhule_charging_start_time', 'dhule_charging_end_time',
                'dhule_kwh', 'dhule_charging_duration', 'idle_time_dhule'
            )
        }),
        ('Return Journey', {
            'fields': (
                'dhar_reach_date', 'dhar_reach_time', 'trip_closed_km',
                'manawar_julwaniya_moving', 'manawar_julwaniya_stoppage', 'manawar_julwaniya_total',
                'julwaniya_dhule_stoppage', 'vehicle_out_time'
            )
        }),
        ('Totals', {
            'fields': (
                'all_station_total_charging_hours', 'vehicle_total_trip_time',
                'total_distance_km', 'total_kwh', 'efficiency_kwh_per_km'
            )
        }),
        ('Trip Performance Metrics', {
            'fields': (
                'trip_duration_s', 'plant_area_time_s', 'plant_area_stop_time_s', 'plant_area_move_time_s',
                'loading_stop_time_s', 'unloading_stop_time_s', 'charging_area_time_s', 'plugged_time_s',
                'charging_area_stop_time_s', 'charging_area_move_time_s', 'unplanned_stoppage_time_s', 'gained_soc'
            ),
            'classes': ('collapse',)
        }),
        ('Raw Data', {
            'fields': ('raw_data',),
            'classes': ('collapse',)
        })
    )


@admin.register(VehicleTripState)
class VehicleTripStateAdmin(admin.ModelAdmin):
    list_display = ('vehicle_no', 'state_date', 'last_cluster', 'last_ts', 'rows_count')
    list_filter = ('state_date', 'last_cluster')
    search_fields = ('vehicle_no',)
    ordering = ('vehicle_no', '-state_date')
    readonly_fields = ('vehicle_no', 'state_date', 'last_cluster', 'last_ts', 'rows_count', 'accumulated_rows_json')

    fieldsets = (
        (None, {
            'fields': ('vehicle_no', 'state_date')
        }),
        ('State Summary', {
            'fields': ('last_cluster', 'last_ts', 'rows_count')
        }),
        ('Raw Accumulated Rows', {
            'fields': ('accumulated_rows_json',),
            'classes': ('collapse',)
        }),
    )


def _fmt_seconds(seconds):
    """Convert a Decimal seconds value to HH:MM for display in admin."""
    if seconds is None:
        return "—"
    s = int(seconds)
    h, m = divmod(s, 3600)
    m //= 60
    return f"{h}h {m:02d}m"


@admin.register(TripPerformanceSummary)
class TripPerformanceSummaryAdmin(admin.ModelAdmin):
    list_display = (
        'month', 'vehicle_no', 'trip_count',
        'avg_trip_duration_hm', 'avg_plant_area_time_hm',
        'avg_loading_stop_time_hm', 'avg_unloading_stop_time_hm',
        'avg_plugged_time_hm', 'avg_unplanned_stoppage_time_hm',
        'avg_gained_soc', 'avg_efficiency_kwh_per_km', 'computed_at',
    )
    list_filter = ('month', 'vehicle_no')
    search_fields = ('vehicle_no', 'month')
    ordering = ('-month', 'vehicle_no')
    readonly_fields = ('computed_at',)

    @admin.display(description="Avg Trip Duration")
    def avg_trip_duration_hm(self, obj):
        return _fmt_seconds(obj.avg_trip_duration_s)

    @admin.display(description="Avg Plant Area")
    def avg_plant_area_time_hm(self, obj):
        return _fmt_seconds(obj.avg_plant_area_time_s)

    @admin.display(description="Avg Loading Stop")
    def avg_loading_stop_time_hm(self, obj):
        return _fmt_seconds(obj.avg_loading_stop_time_s)

    @admin.display(description="Avg Unloading Stop")
    def avg_unloading_stop_time_hm(self, obj):
        return _fmt_seconds(obj.avg_unloading_stop_time_s)

    @admin.display(description="Avg Plugged Time")
    def avg_plugged_time_hm(self, obj):
        return _fmt_seconds(obj.avg_plugged_time_s)

    @admin.display(description="Avg Unplanned Stop")
    def avg_unplanned_stoppage_time_hm(self, obj):
        return _fmt_seconds(obj.avg_unplanned_stoppage_time_s)

    fieldsets = (
        ('Identity', {
            'fields': ('month', 'vehicle_no', 'trip_count', 'computed_at')
        }),
        ('Trip & Efficiency', {
            'fields': ('avg_trip_duration_s', 'avg_efficiency_kwh_per_km')
        }),
        ('Plant Area', {
            'fields': ('avg_plant_area_time_s', 'avg_plant_area_stop_time_s', 'avg_plant_area_move_time_s',
                       'avg_loading_stop_time_s', 'avg_unloading_stop_time_s')
        }),
        ('Charging', {
            'fields': ('avg_charging_area_time_s', 'avg_plugged_time_s',
                       'avg_charging_area_stop_time_s', 'avg_charging_area_move_time_s', 'avg_gained_soc')
        }),
        ('Stoppages', {
            'fields': ('avg_unplanned_stoppage_time_s',)
        }),
    )


@admin.register(FullPipelineRun)
class FullPipelineRunAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'start_date', 'end_date', 'vehicle_no', 'status',
        'trips_calculated', 'trips_saved',
        'summary_months_updated', 'summary_vehicles_updated',
        'duration_seconds', 'started_at', 'ended_at',
    )
    list_filter = ('status', 'start_date')
    search_fields = ('vehicle_no', 'error_message')
    ordering = ('-started_at',)
    readonly_fields = (
        'started_at', 'ended_at', 'duration_seconds',
        'trips_calculated', 'trips_saved',
        'summary_months_updated', 'summary_vehicles_updated',
        'status', 'error_message', 'log',
    )

    fieldsets = (
        ('Run Parameters', {
            'fields': ('start_date', 'end_date', 'vehicle_no')
        }),
        ('Status & Timing', {
            'fields': ('status', 'started_at', 'ended_at', 'duration_seconds', 'error_message')
        }),
        ('Results', {
            'fields': ('trips_calculated', 'trips_saved', 'summary_months_updated', 'summary_vehicles_updated')
        }),
        ('Run Log', {
            'fields': ('log',),
            'classes': ('collapse',)
        }),
    )
