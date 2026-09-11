from django.urls import path
from django.views.generic import RedirectView
from .views import pages, seo, calculators

app_name = 'home'

urlpatterns = [
    path('robots.txt',       seo.robots_txt,        name='robots_txt'),
    path('favicon.ico',      pages.favicon,         name='favicon'),
    path('',                 pages.home,            name='home'),
    path('about/',           pages.about,           name='about'),
    path('faq/',             pages.faq,             name='faq'),
    path('contact/',         pages.contact,         name='contact'),
    path('contact/submit/',  pages.contact_submit,  name='contact_submit'),
    path('find-agents/',     pages.find_agents,     name='find_agents'),
    path('find-agents/ai-picks/', pages.ai_picks_comparison, name='ai_picks_comparison'),
    path('terms/',          pages.terms,          name='terms'),
    path('privacy/',        pages.privacy,        name='privacy'),
    path('insurance/api/pincode/fetch/<str:pincode>', pages.pincode_fetch, name='pincode_fetch'),
    path('api/pincode/check-agents/<str:pincode>', pages.check_pincode_agents, name='check_pincode_agents'),
    path('check-pincode', pages.check_pincode, name='check_pincode'),
    path('marketing/', pages.marketing, name='marketing'),
    path('calculators/', calculators.hub, name='calculators'),
    path('calculators/<slug:slug>/', calculators.detail_or_category, name='calculator_detail'),
    path('calculator/', RedirectView.as_view(url='/calculators/health-insurance-calculator/', permanent=True), name='calculator'),
    path('coming-soon/', pages.coming_soon, name='coming_soon'),
    path('lic-agent/', pages.lic_event, name='lic_event'),
    path('liafi/', pages.liafi_event, name='liafi_event'),
    path('liafi-agent/', RedirectView.as_view(url='/liafi/', permanent=False), name='liafi_agent_redirect'),
    path('cancellation-refund-policy/', pages.cancellation_refund_policy, name='cancellation_refund'),
    path('blacklisted-agents/', pages.blacklisted_agents, name='blacklisted_agents'),
    path('<slug:slug>/',     pages.custom_page,    name='custom_page'),
]
