from django.test import RequestFactory, TestCase

from apps.agents.services.og_urls import build_og_absolute_url, get_public_site_base


class OgUrlCanonicalTests(TestCase):
    def test_www_host_uses_non_www_canonical_origin(self):
        request = RequestFactory().get('/gj/test-agent-1/', HTTP_HOST='www.padosiagent.com')
        base = get_public_site_base(request)
        self.assertEqual(base, 'https://padosiagent.com')
        url = build_og_absolute_url(request, '/og-image/1/preview.jpg')
        self.assertTrue(url.startswith('https://padosiagent.com/'))
        self.assertNotIn('www.', url)
