# monitoring/migrations/0006_systemsettings_maintenance_time.py

from django.db import migrations, models
import django.utils.timezone

class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0005_systemsettings_data_collection_interval'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='maintenance_time',
            field=models.TimeField(
                default=django.utils.timezone.now().replace(hour=0, minute=0, second=0).time(),
                help_text='Час виконання щоденного обслуговування (очищення даних)'
            ),
        ),
    ]