from django.shortcuts import render
from monitoring.models import EnergyLog

def dashboard(request):
    logs = EnergyLog.objects.all().order_by('-timestamp')[:1000]  # last 100 entries
    return render(request, 'dashboard.html', {'logs': logs})