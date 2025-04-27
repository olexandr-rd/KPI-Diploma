# monitoring/migrations/0005_systemsettings_data_collection_interval.py

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0004_user_profiles_and_system_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='data_collection_interval',
            field=models.IntegerField(default=15, help_text='Інтервал збору даних (хвилин)'),
        ),
    ]