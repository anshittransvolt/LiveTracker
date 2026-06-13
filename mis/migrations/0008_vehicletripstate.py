from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mis", "0007_recomputerun"),
    ]

    operations = [
        migrations.CreateModel(
            name="VehicleTripState",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("vehicle_no", models.CharField(db_index=True, max_length=50, verbose_name="Vehicle Number")),
                ("state_date", models.DateField(db_index=True, verbose_name="State As-Of Date")),
                ("accumulated_rows_json", models.TextField(default="[]", verbose_name="Accumulated Rows (JSON)")),
                ("last_cluster", models.CharField(blank=True, max_length=50, null=True, verbose_name="Last Known Cluster")),
                ("last_ts", models.DateTimeField(blank=True, null=True, verbose_name="Last Telemetry Timestamp")),
                ("rows_count", models.IntegerField(default=0, verbose_name="Accumulated Row Count")),
            ],
            options={
                "verbose_name": "Vehicle Trip State",
                "verbose_name_plural": "Vehicle Trip States",
                "db_table": "mis_vehicle_trip_state",
                "ordering": ["-state_date"],
                "indexes": [
                    models.Index(fields=["vehicle_no", "-state_date"], name="mis_vehicletripstate_vehicle_date_idx"),
                ],
            },
        ),
        migrations.AlterUniqueTogether(
            name="vehicletripstate",
            unique_together={("vehicle_no", "state_date")},
        ),
    ]
