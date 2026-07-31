import os
import django
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT COUNT(*) FROM blacklisted_agents")
    count_now = cursor.fetchone()[0]
    print(f"Count after reduced import: {count_now}")
