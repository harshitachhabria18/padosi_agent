from django.urls import path
from .views import pages

app_name = 'home'

urlpatterns = [
    path('favicon.ico',      pages.favicon,         name='favicon'),
    path('',                 pages.home,            name='home'),
    path('about/',           pages.about,           name='about'),
    path('faq/',             pages.faq,             name='faq'),
    path('contact/',         pages.contact,         name='contact'),
    path('contact/submit/',  pages.contact_submit,  name='contact_submit'),
    path('find-agents/',     pages.find_agents,     name='find_agents'),
    path('terms/',          pages.terms,          name='terms'),
    path('privacy/',        pages.privacy,        name='privacy'),
    path('api/pincode/fetch/<str:pincode>', pages.pincode_fetch, name='pincode_fetch'),
    path('<slug:slug>/',     pages.custom_page,    name='custom_page'),
]
