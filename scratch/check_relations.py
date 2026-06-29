import os
import django
import sys

sys.path.append('c:/Users/Ashish/Downloads/10_6/django/padosi_agent')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from apps.agents.models import Agent

def test():
    base = Agent.objects.filter(status='active', user__isnull=False)
    print("Base active agents:", base.count())
    print("With profile:", base.filter(profile__isnull=False).count())
    print("With performanceStats:", base.filter(performanceStats__isnull=False).count())
    
    # Try select_related variations
    print("select_related('user'):", base.select_related('user').count())
    print("select_related('profile'):", base.select_related('profile').count())
    print("select_related('performanceStats'):", base.select_related('performanceStats').count())
    print("select_related('profile', 'performanceStats'):", base.select_related('profile', 'performanceStats').count())

if __name__ == '__main__':
    test()
