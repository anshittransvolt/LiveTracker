# migrations/XXXX_convert_encrypted_to_plain.py
from django.db import migrations, models
from cryptography.fernet import Fernet
import os


def decrypt_data(encrypted_data, key):
    if not encrypted_data:
        return None
    try:
        f = Fernet(key)
        return f.decrypt(encrypted_data.encode()).decode()
    except Exception:
        return None


def migrate_driver_data(apps, schema_editor):
    DriverMaster = apps.get_model("roster", "DriverMaster")
    key = os.getenv("ENCRYPTION_KEY")

    if not key:
        print("Warning: ENCRYPTION_KEY not found, skipping decryption")
        return

    if isinstance(key, str):
        key = key.encode()

    for driver in DriverMaster.objects.all():
        if driver.employee_name_encrypted:
            decrypted_name = decrypt_data(driver.employee_name_encrypted, key)
            if decrypted_name:
                driver.employee_name = decrypted_name

        if driver.phone_encrypted:
            decrypted_phone = decrypt_data(driver.phone_encrypted, key)
            if decrypted_phone:
                driver.phone = decrypted_phone

        driver.save()


def migrate_assignment_data(apps, schema_editor):
    HorseTrolleyAssignment = apps.get_model("roster", "HorseTrolleyAssignment")
    key = os.getenv("ENCRYPTION_KEY")

    if not key:
        print("Warning: ENCRYPTION_KEY not found, skipping decryption")
        return

    if isinstance(key, str):
        key = key.encode()

    for assignment in HorseTrolleyAssignment.objects.all():
        if assignment.driver_name_encrypted:
            decrypted_name = decrypt_data(assignment.driver_name_encrypted, key)
            if decrypted_name:
                assignment.driver_name = decrypted_name

        assignment.save()


class Migration(migrations.Migration):

    dependencies = [
        ("roster", "0002_remove_drivermaster_employee_name_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="drivermaster",
            name="employee_name",
            field=models.CharField(max_length=200, default="", db_index=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="drivermaster",
            name="phone",
            field=models.CharField(max_length=10, blank=True, null=True),
        ),
        migrations.AddField(
            model_name="horsetrolleyassignment",
            name="driver_name",
            field=models.CharField(max_length=200, default=""),
            preserve_default=False,
        ),
        migrations.RunPython(migrate_driver_data),
        migrations.RunPython(migrate_assignment_data),
        migrations.RemoveField(
            model_name="drivermaster",
            name="employee_name_encrypted",
        ),
        migrations.RemoveField(
            model_name="drivermaster",
            name="phone_encrypted",
        ),
        migrations.RemoveField(
            model_name="horsetrolleyassignment",
            name="driver_name_encrypted",
        ),
    ]
