import os
import django
import sys

sys.path.append('c:/Users/Ashish/Downloads/10_6/django/padosi_agent')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from apps.agents.models import Agent

def test():
    try:
        q = Agent.objects.filter(profile__city__icontains="Ahmedabad")
        print("Success, query count:", q.count())
    except Exception as e:
        print("ERROR filtering by profile__city:", e)

if __name__ == '__main__':
    test()
