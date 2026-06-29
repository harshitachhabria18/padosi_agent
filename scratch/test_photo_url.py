import os
import django
import sys

sys.path.append('c:/Users/Ashish/Downloads/10_6/django/padosi_agent')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from apps.agents.models import Agent, AgentProfile, AgentAchievementPhoto
from django.conf import settings

def test():
    # Setup test file under media/app/public/profile/
    os.makedirs(os.path.join(settings.MEDIA_ROOT, 'app/public/profile'), exist_ok=True)
    os.makedirs(os.path.join(settings.MEDIA_ROOT, 'app/public/achievement'), exist_ok=True)
    
    profile_test_filename = 'agent_9999_test.jpg'
    profile_test_filepath = os.path.join(settings.MEDIA_ROOT, 'app/public/profile', profile_test_filename)
    with open(profile_test_filepath, 'w') as f:
        f.write('test')
        
    achievement_test_filename = 'achievement_9999_test.jpg'
    achievement_test_filepath = os.path.join(settings.MEDIA_ROOT, 'app/public/achievement', achievement_test_filename)
    with open(achievement_test_filepath, 'w') as f:
        f.write('test')

    try:
        # Create a mock agent profile and photo path
        agent = Agent.objects.filter(status='active').first()
        if not agent:
            print("No active agent in DB to test with")
            return
            
        profile = agent.profile
        original_photo_path = profile.profile_photo_path
        
        # Test 1: New path with app/public/profile/
        profile.profile_photo_path = f"app/public/profile/{profile_test_filename}"
        print("Set profile_photo_path to:", profile.profile_photo_path)
        print("Resolved profile_photo_url:", profile.profile_photo_url)
        
        # Test 2: Existing path (doesn't start with app/public/)
        profile.profile_photo_path = "profiles/non_existent.jpg"
        print("Set profile_photo_path to:", profile.profile_photo_path)
        print("Resolved profile_photo_url (fallback):", profile.profile_photo_url)
        
        # Restore original
        profile.profile_photo_path = original_photo_path
        
        # Test 3: Achievement photo URL resolution
        achievement_photo = AgentAchievementPhoto(agent=agent, photo_path=f"app/public/achievement/{achievement_test_filename}")
        print("Set achievement photo_path to:", achievement_photo.photo_path)
        print("Resolved achievement photo_url:", achievement_photo.photo_url)
        
    finally:
        # Clean up test files
        if os.path.exists(profile_test_filepath):
            os.remove(profile_test_filepath)
        if os.path.exists(achievement_test_filepath):
            os.remove(achievement_test_filepath)

if __name__ == '__main__':
    test()
