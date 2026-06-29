import os
import django
import sys

sys.path.append('c:/Users/Ashish/Downloads/10_6/django/padosi_agent')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from apps.agents.models import Agent
from django.contrib.auth.models import User

def test():
    agents = Agent.objects.filter(status='active')
    print("Total active agents:", agents.count())
    matching_user_count = 0
    for agent in agents:
        if agent.user_id is not None:
            user_exists = User.objects.filter(id=agent.user_id).exists()
            if user_exists:
                matching_user_count += 1
                print(f"Agent {agent.fullname} has user {agent.user_id} in auth_user")
    print("Active agents with matching user in auth_user:", matching_user_count)

if __name__ == '__main__':
    test()
