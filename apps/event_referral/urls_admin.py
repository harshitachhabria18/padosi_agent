from django.urls import path

from apps.event_referral.views import admin_views

urlpatterns = [
    path('', admin_views.admin_dashboard, name='admin_event_referral_dashboard'),
    path('settings/update/', admin_views.admin_update_settings, name='admin_event_referral_settings'),
    path('toggle/', admin_views.admin_toggle_registration, name='admin_event_referral_toggle'),
    path('participants/<int:participant_id>/extend/', admin_views.admin_extend_deadline, name='admin_event_referral_extend'),
    path('participants/<int:participant_id>/target/', admin_views.admin_update_target, name='admin_event_referral_target'),
    path('participants/<int:participant_id>/grant/', admin_views.admin_grant_plan, name='admin_event_referral_grant'),
    path('participants/<int:participant_id>/block/', admin_views.admin_block_participant, name='admin_event_referral_block'),
    path('participants/<int:participant_id>/restore/', admin_views.admin_restore_participant, name='admin_event_referral_restore'),
]
