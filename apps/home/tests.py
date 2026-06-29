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

