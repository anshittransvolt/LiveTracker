from django.db import models


class FleetTrendDaily(models.Model):
    """
    Precomputed daily trend data for the Fleet Trend bottom bar.
    vehicle_no=NULL  → fleet-wide average for that (date, spv).
    vehicle_no=REG   → per-vehicle record for fast vehicle-click trend.
    Populated nightly by APScheduler at 02:00 AM IST.
    """
    date = models.DateField(db_index=True)
    spv = models.CharField(max_length=50, db_index=True)
    vehicle_no = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    avg_distance_km = models.FloatField(null=True)
    avg_energy_kwh = models.FloatField(null=True)
    avg_efficiency_kwh_per_km = models.FloatField(null=True)
    vehicle_count = models.IntegerField(default=0)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("date", "spv", "vehicle_no")]
        ordering = ["date"]

    def __str__(self) -> str:
        target = self.vehicle_no or "fleet"
        return f"{self.spv}/{target} {self.date}: dist={self.avg_distance_km} km"
