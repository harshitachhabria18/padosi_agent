from django.test import TestCase
from django.urls import reverse
from apps.home.models.site_setting import SiteSetting
from apps.admin_panel.models.admin_activity_log import AdminActivityLog

class AdminAboutPageTests(TestCase):
    def test_admin_about_page_status_code(self):
        response = self.client.get(reverse('admin_panel:content_about'))
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
        
        response = self.client.post(reverse('admin_panel:content_about_update'), data=update_data)
        self.assertRedirects(response, reverse('admin_panel:content_about'))
        
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
    def test_settings_pages_status_code(self):
        response = self.client.get(reverse('admin_panel:settings_homepage'))
        self.assertEqual(response.status_code, 200)

        response_hero = self.client.get(reverse('admin_panel:settings_hero_section'))
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
        response = self.client.post(reverse('admin_panel:settings_homepage_update'), data=post_data)
        self.assertRedirects(response, reverse('admin_panel:settings_homepage'))

        # Verify SiteSetting database update
        setting_val = SiteSetting.get_value('homepage_content')
        self.assertEqual(setting_val['hero']['headline'], 'Super Headline')
        self.assertTrue(setting_val['hero']['visible'])
        self.assertEqual(setting_val['dyk']['slides'][0]['title'], 'Fast settlements')

        # Verify activity log creation
        logs = AdminActivityLog.objects.filter(action='Update homepage content')
        self.assertEqual(logs.count(), 1)

