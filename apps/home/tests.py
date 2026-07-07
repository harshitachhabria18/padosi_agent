from django.test import TestCase
from django.urls import reverse
from apps.home.models.site_setting import SiteSetting

class AboutPageTests(TestCase):
    def test_about_page_status_code(self):
        response = self.client.get(reverse('home:about'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "About Us")

    def test_about_page_custom_content(self):
        # Set custom about page content in SiteSetting model
        custom_content = {
            'banner_title': 'Custom About Title',
            'banner_subtitle': 'Custom subtitle text',
            'who_we_are': 'We are insurance helpers.',
            'why_we_exist': 'To assist you.',
            'what_we_do': 'We provide discovering.',
            'vision': 'Our custom vision.',
            'mission': 'Our custom mission.',
            'commitment': 'Our custom commitment.',
        }
        SiteSetting.set_value('about_page_content', custom_content, 'about')
        
        response = self.client.get(reverse('home:about'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Custom About Title")
        self.assertContains(response, "Custom subtitle text")
        self.assertContains(response, "We are insurance helpers.")
        self.assertContains(response, "Our custom vision.")


class HomePageTests(TestCase):
    def test_home_page_status_code(self):
        response = self.client.get(reverse('home:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Insurance Expert")

    def test_home_page_custom_settings(self):
        custom_hero = {
            'heading': 'Our {Trusted} Team in your {Padosi}'
        }
        SiteSetting.set_value('hero_section', custom_hero, 'homepage')
        response = self.client.get(reverse('home:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Our <span class=\"pa-heading-trusted\">Trusted</span> Team")


class FooterTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_footer_dynamic_rendering_and_caching(self):
        # Set settings in DB
        SiteSetting.set_value('contact_email', 'test_support@padosiagent.com')
        SiteSetting.set_value('contact_address', '123 Test Street, Test City')
        social_links = {
            'facebook': 'https://facebook.com/testpage',
            'twitter': 'https://twitter.com/testpage',
            'instagram': '#', # should be hidden
            'linkedin': '', # should be hidden
        }
        SiteSetting.set_value('social_links', social_links)
        SiteSetting.set_value('site_name', 'TestPadosi')

        # Request a page to render footer
        response = self.client.get(reverse('home:home'))
        self.assertEqual(response.status_code, 200)

        # Check rendered values
        self.assertContains(response, 'test_support@padosiagent.com')
        self.assertContains(response, '123 Test Street, Test City')
        self.assertContains(response, 'https://facebook.com/testpage')
        self.assertContains(response, 'https://twitter.com/testpage')
        
        # Instagram and linkedin are empty or '#', they should be hidden
        self.assertNotContains(response, 'fa-instagram')
        self.assertNotContains(response, 'fa-linkedin')

        # Check that the copyright has the dynamic website name
        self.assertContains(response, 'TestPadosi')

        # Verify cached data exists
        from django.core.cache import cache
        cached_data = cache.get('footer_settings_data')
        self.assertIsNotNone(cached_data)
        self.assertEqual(cached_data['contact_email'], 'test_support@padosiagent.com')

        # Clear/Update setting and verify cache invalidation signal
        SiteSetting.set_value('contact_email', 'new_support@padosiagent.com')
        
        # The cache key 'footer_settings_data' should be gone (cleared by signal)
        self.assertIsNone(cache.get('footer_settings_data'))

        # Request again and check new value is rendered and cached
        response2 = self.client.get(reverse('home:home'))
        self.assertContains(response2, 'new_support@padosiagent.com')
        self.assertNotContains(response2, 'test_support@padosiagent.com')
        
        cached_data2 = cache.get('footer_settings_data')
        self.assertIsNotNone(cached_data2)
        self.assertEqual(cached_data2['contact_email'], 'new_support@padosiagent.com')


