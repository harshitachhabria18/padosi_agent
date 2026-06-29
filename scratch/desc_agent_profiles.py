import os
import django
import sys

sys.path.append('c:/Users/Ashish/Downloads/10_6/django/padosi_agent')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from django.db import connection

def test():
    with connection.cursor() as cursor:
        cursor.execute("DESCRIBE `agent_profiles`")
        print("agent_profiles columns:")
        for row in cursor.fetchall():
            print(row)

if __name__ == '__main__':
    test()
