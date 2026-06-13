
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('livetracker', '0008_livetrackeralertaction'),
    ]

    operations = [
        migrations.DeleteModel(
            name='AlertAction',
        ),
    ]
