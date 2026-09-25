from django.urls import path, re_path
from django.views.decorators.csrf import csrf_exempt
from .views import registration, auth, dashboard, gbp as gbp_views, bio_generator, favorites, participants, career_timeline as career_timeline_views, qr as qr_views, analytics as analytics_views

app_name = 'agents'

urlpatterns = [
    path('agent-registration/join/<str:ref_code>/', registration.agent_registration_referral, name='agent_registration_referral'),
    path('agent-registration/', registration.agent_registration, name='agent_registration'),
    path('register/',           registration.agent_registration, name='register_alias'),
    path('agent-register-step1/', registration.register_step1,   name='agent_register_step1'),
    path('agent-register-step2/', registration.register_step2,   name='agent_register_step2'),
    path('agent-check-slug/',     registration.check_slug_availability, name='agent_check_slug'),
    path('agent-check-email/',    registration.check_email_availability, name='agent_check_email'),
    path('chooseplan/',         registration.chooseplan,         name='chooseplan'),
    path('plan-social-follow/', registration.record_social_follow, name='plan_social_follow'),
    path('plan-scratch-reveal/', registration.record_scratch_reveal, name='plan_scratch_reveal'),
    path('exclusive-plan/social-follow/', registration.record_social_follow, name='exclusive_social_follow'),
    path('exclusive-plan/discount-status/', registration.exclusive_discount_status, name='exclusive_discount_status'),
    path('agent-register-complete/', registration.agent_register_complete, name='agent_register_complete'),
    path('agent-register/complete/', registration.agent_register_complete, name='agent_register_complete_slash'),
    path('agent-register/verify-payment/', registration.payment_success, name='agent_register_verify_payment'),
    path('agent-register/payment-callback/', csrf_exempt(registration.payment_callback), name='agent_register_payment_callback'),
    path('agent-register/payment-complete/', registration.payment_complete, name='payment_complete'),
    path('payment-success/',    registration.payment_success,    name='payment_success'),
    path('payment-failure/',    registration.payment_failure,    name='payment_failure'),
    path('agent-registration/failed/', registration.agent_register_failed, name='agent_register_failed'),
    path('razorpay-webhook/',   csrf_exempt(registration.razorpay_webhook), name='razorpay_webhook'),
    path('agent/verify-promo/', registration.agent_verify_promo, name='agent_verify_promo'),
    path('agent/clear-promo/',  registration.agent_clear_promo,  name='agent_clear_promo'),
    path('agent-login/',        auth.agent_login,                name='agent_login'),
    path('forgot-password/',    auth.forgot_password,            name='forgot_password'),
    path('reset-password/<str:uidb64>/<str:token>/', auth.reset_password, name='reset_password'),
    path('agent-logout/',       auth.agent_logout,               name='agent_logout'),
    path('logout/',             auth.logout_view,                name='logout'),
    path('agent/dashboard/',    dashboard.agent_dashboard,       name='agent_dashboard'),
    path('agent/review-card/',  qr_views.agent_review_card_redirect, name='agent_review_card_me'),
    path('review/<str:slug>/',  qr_views.public_review_page,     name='agent_public_review'),
    path('review-card/<str:slug>/', qr_views.public_review_card, name='agent_review_card'),
    path('agent/referral/',     dashboard.referral,              name='agent_referral'),
    re_path(r'^agent/qr/(?P<qr_type>profile|card|reviews)\.png$', qr_views.agent_qr_image, name='agent_qr_image'),
    path('agent/qr/<str:qr_type>/download/', qr_views.agent_qr_download, name='agent_qr_download'),
    # Review routes must come before profile/<state>/<slug>/, otherwise
    # POST /profile/<slug>/review/ is captured as state_code=slug, slug="review"
    # and agent_public_profile 404s looking up slug "review".
    path('profile/<str:slug>/review/', dashboard.store_review,   name='agent_store_review'),
    path('profile/<str:state_code>/<str:slug>/review/', dashboard.store_review,   name='agent_store_review_state'),
    path('profile/<str:slug>/', dashboard.agent_public_profile,  name='agent_public_profile'),
    path('profile/<str:state_code>/<str:slug>/', dashboard.agent_public_profile,  name='agent_public_profile_state'),
    path('card/<str:slug>/',    qr_views.public_agent_card,      name='agent_public_card'),
    re_path(r'^qr/(?P<slug>[^/]+)/(?P<qr_type>profile|card|reviews)\.png$', qr_views.public_qr_image, name='agent_public_qr_image'),
    path('agent/edit-profile/', dashboard.edit_profile,         name='agent_edit_profile'),
    path('agent/update-profile/', dashboard.update_profile,     name='agent_update_profile'),
    path('agent/push-token/',   dashboard.agent_push_token,      name='agent_push_token'),
    path('agent/upgrade-plan/', dashboard.agent_upgrade_plan,    name='agent_upgrade_plan'),
    path('agent/referral-info/', dashboard.referral_info,        name='agent_referral_info'),
    path('join/ad/', registration.fb_ad_signup, name='fb_ad_signup'),
    path('join/<str:ref_code>/', registration.referral_join,     name='referral_join'),
    path('auth/google/', auth.redirectToGoogle,                  name='google_auth'),
    path('auth/google/callback/', auth.handleGoogleCallback,    name='google_auth_callback'),
    path('auth/google/get-session-data/', auth.getGoogleSessionData, name='google_auth_get_session_data'),
    path('auth/google/user-data/', auth.getGoogleUserData,      name='google_auth_user_data'),
    path('auth/google/clear-session/', auth.clearGoogleSession,  name='google_auth_clear_session'),
    path('agent/leads/capture/', dashboard.agent_capture_lead,   name='agent_leads_capture'),
    path('agent/leads/update-status/', dashboard.update_lead_status, name='update_lead_status'),
    path('agent/update-visibility/', dashboard.agent_update_visibility, name='agent_update_visibility'),
    path('client/quick-register/', registration.client_quick_register, name='client_quick_register'),
    path('og-image/<int:agent_id>/preview.jpg', dashboard.agent_og_image, name='agent_og_image'),
    path('og-image/<int:agent_id>/og.jpg', dashboard.agent_og_image),
    path('og-image/<str:slug>/preview.jpg', dashboard.agent_og_image, name='agent_og_image_slug'),
    path('og-image/<str:slug>/og.jpg', dashboard.agent_og_image),

    # ── Google Business Profile OAuth & API ──────────────────────────────────
    path('agent/gbp/auth/',     gbp_views.agent_gbp_auth,     name='agent_gbp_auth'),
    path('agent/gbp/callback/', gbp_views.agent_gbp_callback, name='agent_gbp_callback'),
    path('agent/gbp/status/',   gbp_views.agent_gbp_status,   name='agent_gbp_status'),
    path('agent/gbp/save-url/', gbp_views.agent_gbp_save_url, name='agent_gbp_save_url'),

    # ── AI Bio Generator ─────────────────────────────────────────────────────
    path('agent/generate-bio/', bio_generator.generate_professional_bio, name='agent_generate_bio'),
    path('agent/toggle-favorite/', favorites.toggle_favorite, name='agent_toggle_favorite'),

    # ── Participants + Facebook share (mirrors routes/web.php:547-569) ─────────
    # Laravel paths are slashless and the ported coming-soon JS posts slashless
    # URLs (fetch('/participants'), `/participants/{sid}/mark-shared`).
    # APPEND_SLASH cannot redirect POST bodies, so register both spellings.
    path('participants', participants.participants_router, name='participants_index'),
    path('participants/', participants.participants_router, name='participants_index_slash'),
    path('participants/create/', participants.participants_create, name='participants_create'),
    path('participants/share/<str:shareable_id>/', participants.participant_share, name='participants_share'),
    path('participants/<int:participant_id>/', participants.participant_show, name='participants_show'),
    path('participants/<str:shareable_id>/mark-shared', participants.mark_as_shared, name='participants_mark_shared'),
    path('participants/<str:shareable_id>/mark-shared/', participants.mark_as_shared, name='participants_mark_shared_slash'),

    # ── Facebook auto-post API ───────────────────────────────────────────────
    path('api/facebook/auto-post/', participants.facebook_auto_post, name='facebook_auto_post'),
    path('api/facebook/verify-post/', participants.facebook_verify_post, name='facebook_verify_post'),
    path('api/facebook/store-token/', participants.facebook_store_token, name='facebook_store_token'),
    path('api/facebook/connection-status/<int:participant_id>/', participants.facebook_connection_status, name='facebook_connection_status'),
    path('api/facebook/confirm-manual-share/', participants.facebook_confirm_manual_share, name='facebook_confirm_manual_share'),

    # ── Career Timeline API (read-only) ──────────────────────────────────────
    path('agent/career-timeline/suggestions/', career_timeline_views.career_timeline_suggestions, name='agent_career_timeline_suggestions'),

    # ── Profile Analytics API ────────────────────────────────────────────
    path('agent/api/analytics/', analytics_views.agent_analytics_data, name='agent_analytics_data'),

    # ── Catch-all public agent profile share route ────────────────────────────
    path('agent/<str:slug>/',   dashboard.agent_public_share_profile, name='agent_public_share_profile'),

    # ── Direct state-prefixed agent profile routes (e.g. /gj/ashish-prajapati/) ──
    re_path(r'^(?P<state_code>[a-zA-Z]{2})/(?P<slug>[a-zA-Z0-9_-]+)/review/$', dashboard.store_review, name='agent_store_review_state_direct'),
    re_path(r'^(?P<state_code>[a-zA-Z]{2})/(?P<slug>[a-zA-Z0-9_-]+)/$', dashboard.agent_public_profile, name='agent_public_profile_state_direct'),
]

