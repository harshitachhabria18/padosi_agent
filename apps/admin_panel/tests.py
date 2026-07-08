import uuid
from django.test import TestCase
from django.urls import reverse
from django.db import connection
from apps.home.models.site_setting import SiteSetting
from apps.admin_panel.models.admin_activity_log import AdminActivityLog

def authenticate_client(client):
    # Ensure admins table has correct schema in SQLite test db by recreating it
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS admins")
        cursor.execute("""
            CREATE TABLE admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name VARCHAR(255), 
                email VARCHAR(255), 
                password VARCHAR(255), 
                role VARCHAR(50), 
                created_at DATETIME, 
                updated_at DATETIME
            )
        """)
        # Clear existing data to avoid conflict
        cursor.execute("DELETE FROM user_sessions")
        cursor.execute("DELETE FROM user_session_data")
        
        # Insert admin
        cursor.execute("INSERT INTO admins (id, name, email, password, role) VALUES (1, 'Admin', 'admin@test.com', 'password', 'super')")
        
        # Insert session (setting expires_at in the far future to pass the date check)
        session_token = str(uuid.uuid4())
        cursor.execute("INSERT INTO user_sessions (id, session_token, ip_address, user_agent, expires_at) VALUES (1, %s, '127.0.0.1', 'test-agent', '2030-01-01 00:00:00')", [session_token])
        
        # Insert session data
        cursor.execute("INSERT INTO user_session_data (session_id, data_key, data_value) VALUES (1, 'admin_id', '1')")
        
    client.cookies['session_token'] = session_token

class AdminAboutPageTests(TestCase):
    def setUp(self):
        authenticate_client(self.client)

    def test_admin_about_page_status_code(self):
        response = self.client.get(reverse('admin_content_about'))
        self.assertEqual(response.status_code, 200)

    def test_admin_about_page_update(self):
        update_data = {
            'banner_title': 'New Banner Title',
            'banner_subtitle': 'New Banner Subtitle',
            'who_we_are': 'New Who We Are',
            'why_we_exist': 'New Why We Exist',
            'what_we_do': 'New What We Do',
            'vision': 'New Vision',
            'mission': 'New Mission',
            'commitment': 'New Commitment',
        }
        
        response = self.client.post(reverse('admin_content_about_update'), data=update_data)
        self.assertRedirects(response, reverse('admin_content_about'))
        
        # Verify SiteSetting database update
        setting_val = SiteSetting.get_value('about_page_content')
        self.assertEqual(setting_val['banner_title'], 'New Banner Title')
        self.assertEqual(setting_val['who_we_are'], 'New Who We Are')
        
        # Verify activity log creation
        logs = AdminActivityLog.objects.all()
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs[0].action, 'Update about page content')
        self.assertEqual(logs[0].model_type, 'SiteSetting')


class AdminHomepageSettingsTests(TestCase):
    def setUp(self):
        authenticate_client(self.client)

    def test_settings_pages_status_code(self):
        response = self.client.get(reverse('admin_settings_homepage'))
        self.assertEqual(response.status_code, 200)

        response_hero = self.client.get(reverse('admin_settings_hero_section'))
        self.assertEqual(response_hero.status_code, 200)

    def test_settings_homepage_update_nested_post(self):
        post_data = {
            'homepage_content[hero][headline]': 'Super Headline',
            'homepage_content[hero][subheadline]': 'Super Sub',
            'homepage_content[hero][visible]': '1',
            'homepage_content[dyk][slides][0][accent]': 'accent-emerald',
            'homepage_content[dyk][slides][0][bg]': 'bg-emerald-500',
            'homepage_content[dyk][slides][0][icon]': 'users',
            'homepage_content[dyk][slides][0][title]': 'Fast settlements',
            'homepage_content[dyk][slides][0][body]': 'Settled in 3 days.',
            'homepage_content[dyk][visible]': '1',
        }
        response = self.client.post(reverse('admin_settings_homepage_update'), data=post_data)
        self.assertRedirects(response, reverse('admin_settings_homepage'))

        # Verify SiteSetting database update
        setting_val = SiteSetting.get_value('homepage_content')
        self.assertEqual(setting_val['hero']['headline'], 'Super Headline')
        self.assertTrue(setting_val['hero']['visible'])
        self.assertEqual(setting_val['dyk']['slides'][0]['title'], 'Fast settlements')

        # Verify activity log creation
        logs = AdminActivityLog.objects.filter(action='Update homepage content')
        self.assertEqual(logs.count(), 1)
