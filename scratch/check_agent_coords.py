import os
import django
import sys

sys.path.append('c:/Users/Ashish/Downloads/10_6/django/padosi_agent')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from apps.agents.models import Agent

def test():
    agents = Agent.objects.filter(status='active')
    print(f"Total active agents: {agents.count()}")
    for agent in agents:
        profile = getattr(agent, 'profile', None)
        city = profile.city if profile else 'No Profile'
        pincodes = profile.service_pincodes if profile else 'None'
        print(f"ID: {agent.id}, Name: {agent.fullname}, Lat/Lng: ({agent.latitude}, {agent.longitude}), City: {city}, Pincodes: {pincodes}")

if __name__ == '__main__':
    test()
