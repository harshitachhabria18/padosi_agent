import os
import django
import sys

sys.path.append('c:/Users/Ashish/Downloads/10_6/django/padosi_agent')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from apps.agents.models import Agent
from django.db.models.expressions import RawSQL

def test():
    base = Agent.objects.filter(status='active', user__isnull=False)
    
    # Without RawSQL
    q_no_raw = base.select_related('profile', 'performanceStats', 'user')
    print("Without RawSQL:", q_no_raw.count(), len(list(q_no_raw)))
    
    # With a simple RawSQL annotation
    q_simple_raw = base.select_related('profile', 'performanceStats', 'user').annotate(test_rank=RawSQL('1', []))
    print("With simple RawSQL:", q_simple_raw.count(), len(list(q_simple_raw)))
    
    # Let's run a query to get actual MySQL error if there is one
    from django.db import connection
    cursor = connection.cursor()
    
    # Try printing the SQL for simple raw
    print("Simple raw SQL:")
    print(q_simple_raw.query)
    
    try:
        list(q_simple_raw)
    except Exception as e:
        print("Error executing simple raw:", e)

if __name__ == '__main__':
    test()
