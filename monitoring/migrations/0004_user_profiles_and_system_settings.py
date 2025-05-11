# monitoring/migrations/0004_user_profiles_and_system_settings.py

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('monitoring', '0003_alter_backuplog_status_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('regular', 'Звичайний користувач'), ('manager', 'Менеджер'), ('admin', 'Системний адміністратор')], default='regular', max_length=20)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='profile', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='SystemSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('backup_frequency_hours', models.IntegerField(default=24, help_text='Частота створення резервних копій (годин)')),
                ('backup_retention_days', models.IntegerField(default=30, help_text='Зберігати резервні копії (днів)')),
                ('max_backups', models.IntegerField(default=20, help_text='Максимальна кількість резервних копій')),
                ('min_load_threshold', models.FloatField(default=500, help_text='Мінімальне допустиме навантаження (Вт)')),
                ('max_load_threshold', models.FloatField(default=2000, help_text='Максимальне допустиме навантаження (Вт)')),
                ('max_energy_logs', models.IntegerField(default=5000, help_text='Максимальна кількість записів енергосистеми')),
                ('last_modified', models.DateTimeField(auto_now=True)),
                ('modified_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Налаштування системи',
                'verbose_name_plural': 'Налаштування системи',
            },
        ),
        migrations.AddField(
            model_name='backuplog',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Створено користувачем'),
        ),
        migrations.AddField(
            model_name='energylog',
            name='anomaly_reason',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Причина аномалії'),
        ),
        migrations.AddField(
            model_name='energylog',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Створено користувачем'),
        ),
        migrations.AddField(
            model_name='energylog',
            name='is_manual',
            field=models.BooleanField(default=False, verbose_name='Ручний запис'),
        ),
        migrations.AlterField(
            model_name='backuplog',
            name='backup_file',
            field=models.CharField(max_length=255, verbose_name='Файл'),
        ),
        migrations.AlterField(
            model_name='backuplog',
            name='error_message',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Повідомлення про помилку'),
        ),
        migrations.AlterField(
            model_name='backuplog',
            name='size_kb',
            field=models.FloatField(default=0, verbose_name='Розмір (КБ)'),
        ),
        migrations.AlterField(
            model_name='backuplog',
            name='status',
            field=models.CharField(choices=[('SUCCESS', 'Успіх'), ('FAILED', 'Помилка')], max_length=20, verbose_name='Статус'),
        ),
        migrations.AlterField(
            model_name='backuplog',
            name='timestamp',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Час створення'),
        ),
        migrations.AlterField(
            model_name='backuplog',
            name='trigger_reason',
            field=models.CharField(choices=[('ANOMALY', 'Аномалія'), ('PREDICTION', 'Прогноз навантаження'), ('MANUAL', 'Ручне копіювання'), ('SCHEDULED', 'За розкладом'), ('UNKNOWN', 'Невідома причина')], max_length=20, verbose_name='Причина'),
        ),
        migrations.AlterField(
            model_name='backuplog',
            name='triggered_by',
            field=models.ManyToManyField(blank=True, related_name='backups', to='monitoring.energylog', verbose_name='Спричинено записами'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='ac_output_voltage',
            field=models.FloatField(verbose_name='Вихідна напруга (В)'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='anomaly_score',
            field=models.FloatField(blank=True, null=True, verbose_name='Оцінка аномалії'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='backup_triggered',
            field=models.BooleanField(default=False, verbose_name='Резервна копія'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='dc_battery_current',
            field=models.FloatField(verbose_name='Струм батареї (А)'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='dc_battery_voltage',
            field=models.FloatField(verbose_name='Напруга батареї (В)'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='is_anomaly',
            field=models.BooleanField(default=False, verbose_name='Аномалія'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='load_power',
            field=models.FloatField(verbose_name='Навантаження (Вт)'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='predicted_load',
            field=models.FloatField(blank=True, null=True, verbose_name='Прогнозоване навантаження (Вт)'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='temperature',
            field=models.FloatField(blank=True, null=True, verbose_name='Температура (°C)'),
        ),
        migrations.AlterField(
            model_name='energylog',
            name='timestamp',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Час запису'),
        ),
        migrations.AlterModelOptions(
            name='backuplog',
            options={'verbose_name': 'Резервна копія', 'verbose_name_plural': 'Резервні копії'},
        ),
        migrations.AlterModelOptions(
            name='energylog',
            options={'verbose_name': 'Запис енергосистеми', 'verbose_name_plural': 'Записи енергосистеми'},
        ),
    ]