import os
import django
import sys

# Add root folder to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT COUNT(*) FROM blacklisted_agents")
    count_before = cursor.fetchone()[0]
    print(f"Count before truncate: {count_before}")
    
    cursor.execute("TRUNCATE TABLE blacklisted_agents")
    print("Table truncated.")
