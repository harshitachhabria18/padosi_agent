"""
URL configuration for padosiagent project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.agents.views.dashboard import serve_private_file
from apps.agents.views import pwa as pwa_views

from django.contrib.auth import views as auth_views
from django.contrib.sitemaps.views import sitemap
from padosi_agent.sitemaps import sitemaps
from padosi_agent.views import csrf_refresh_api

urlpatterns = [
    path('api/v1/csrf-refresh/', csrf_refresh_api, name='csrf_refresh_api'),
    # ── PWA (mirrors Laravel pwa.manifest / pwa.sw / pwa.offline) ────────────
    path('manifest.webmanifest', pwa_views.manifest,       name='pwa.manifest'),
    path('sw.js',                pwa_views.service_worker, name='pwa.sw'),
    path('offline.html',         pwa_views.offline,        name='pwa.offline'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('insurance-login/', auth_views.LoginView.as_view(template_name='insurance/login.html', redirect_authenticated_user=True), name='insurance_login'),
    # Removed overriding logout view, now handled by apps.agents.urls
    path('media/app/private/<path:file_path>', serve_private_file, name='serve_private_file'),
    path('django-admin/', admin.site.urls),
    path('agent/championship/', include('apps.referral_championship.urls')),
    path('admin/championship/', include('apps.referral_championship.urls_admin')),
    path('event-registration/', include('apps.event_referral.urls')),
    path('admin/event-referral/', include('apps.event_referral.urls_admin')),
    path('', include('apps.admin_panel.urls')),
    path('', include('apps.agents.urls')),
    path('events/', include('apps.agents.urls_events')),
    path('chatbot-api/', include('apps.chatbot.urls')),
    path('', include('apps.distributors.urls')),
    path('insurance/', include('apps.insurance.urls')),
    path('', include('apps.home.urls')),
]

import posixpath

from django.http import Http404
from django.views.static import serve
from django.urls import re_path


def serve_public_media(request, path, document_root=None):
    """static.serve for public media that never exposes app/private/.

    serve() normalises the path itself, so "/media/app//private/x.pdf" missed
    the authenticated private route above yet was served from app/private.
    """
    normalized = posixpath.normpath(path.replace('\\', '/')).lstrip('/')
    if normalized == 'app/private' or normalized.startswith('app/private/'):
        raise Http404("File not found")
    response = serve(request, path, document_root=document_root)
    # User uploads must never execute as same-origin documents (HTML/SVG
    # uploaded as a "photo" was stored XSS). Embedding via <img> is unaffected;
    # PDFs are exempt so license documents still open in the browser viewer.
    response['X-Content-Type-Options'] = 'nosniff'
    if not normalized.lower().endswith('.pdf'):
        response['Content-Security-Policy'] = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
    return response


# Serve media files in development & production fallback
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve_public_media, {'document_root': settings.MEDIA_ROOT}),
]


