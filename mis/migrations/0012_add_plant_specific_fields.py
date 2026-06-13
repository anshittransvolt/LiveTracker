# Generated manually for plant-specific loading/unloading fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mis', '0011_full_pipeline_run'),
    ]

    operations = [
        migrations.AddField(
            model_name='calculatedtrip',
            name='manawar_loading_entry_date',
            field=models.DateField(blank=True, null=True, verbose_name='Manawar Load Entry Date'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='manawar_loading_entry_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Manawar Load Entry Time'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='manawar_loading_exit_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Manawar Load Exit Time'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='extra_time_after_loading',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='Extra Time After Loading (HH:MM)'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='dhule_unload_date',
            field=models.DateField(blank=True, null=True, verbose_name='Dhule Unload Date'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='dhule_unload_entry_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Dhule Unload Entry Time'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='dhule_unload_exit_date',
            field=models.DateField(blank=True, null=True, verbose_name='Dhule Unload Exit Date'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='dhule_unload_exit_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Dhule Unload Exit Time'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='dhule_unload_time',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='Dhule Unload Time (HH:MM)'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='dhule_plant_unload',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='Dhule Plant Unload Time (HH:MM)'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='stoppage_d_j_m',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='Stoppage D→J→M (HH:MM)'),
        ),
        migrations.AddField(
            model_name='calculatedtrip',
            name='road_time_to_dhar',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='Road Time to Dhar (HH:MM)'),
        ),
    ]