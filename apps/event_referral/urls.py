from django.urls import path

from apps.event_referral.views import registration

app_name = 'event_referral'

urlpatterns = [
    path('', registration.event_registration, name='register'),
]
