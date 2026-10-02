from django.urls import path

from apps.event_referral.views import registration
from apps.event_referral.views import public_leaderboard

app_name = 'event_referral'

urlpatterns = [
    path('', registration.event_registration, name='register'),
    path('leaderboard/', public_leaderboard.public_leaderboard, name='public_leaderboard'),
]
