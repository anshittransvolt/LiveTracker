from django.db import models


class TimeBoxDailyAvgDelay(models.Model):
    """
    Stores precomputed fleet-wide average delay (in minutes) for a given calendar day.
    Used to serve the TIME BOX trend series quickly without recomputation.
    """
    date = models.DateField(unique=True, db_index=True)
    avg_delay_minutes = models.IntegerField(default=0)
    vehicle_count = models.IntegerField(default=0)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date"]

    def __str__(self) -> str:
        return f"{self.date} = {self.avg_delay_minutes} min"

    @property
    def avg_delay_hhmm(self) -> str:
        h = (self.avg_delay_minutes // 60)
        m = (self.avg_delay_minutes % 60)
        return f"{h:02d}:{m:02d}"
