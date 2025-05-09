# monitoring/migrations/0008_update_energy_model.py

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('monitoring', '0007_alter_systemsettings_maintenance_time'),
    ]

    operations = [
        # Remove fields
        migrations.RemoveField(
            model_name='systemsettings',
            name='min_load_threshold',
        ),
        migrations.RemoveField(
            model_name='systemsettings',
            name='max_load_threshold',
        ),
        migrations.RemoveField(
            model_name='energylog',
            name='predicted_load',
        ),

        # Add new fields
        migrations.AddField(
            model_name='energylog',
            name='predicted_current',
            field=models.FloatField(blank=True, null=True, verbose_name='Прогнозований струм (А)'),
        ),
        migrations.AddField(
            model_name='energylog',
            name='predicted_voltage',
            field=models.FloatField(blank=True, null=True, verbose_name='Прогнозована напруга (В)'),
        ),
        migrations.AddField(
            model_name='energylog',
            name='is_abnormal_prediction',
            field=models.BooleanField(default=False, verbose_name='Аномальний прогноз'),
        ),

        # Update verbose names for existing fields to match new terminology
        migrations.AlterField(
            model_name='energylog',
            name='load_power',
            field=models.FloatField(verbose_name='Навантаження (Вт)'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='temperature',
            field=models.FloatField(blank=True, null=True, verbose_name='Температура акумулятора (°C)'),
        ),

        # Update BackupLog choices to replace PREDICTION with new terminology
        migrations.AlterField(
            model_name='backuplog',
            name='trigger_reason',
            field=models.CharField(
                choices=[
                    ('ANOMALY', 'Аномалія'),
                    ('PREDICTION', 'Аномальний прогноз'),
                    ('MANUAL', 'Ручне копіювання'),
                    ('SCHEDULED', 'За розкладом'),
                    ('UNKNOWN', 'Невідома причина')
                ],
                max_length=20,
                verbose_name='Причина'
            ),
        ),
    ]