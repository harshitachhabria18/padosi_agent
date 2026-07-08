"""
apps/admin_panel/urls.py

Phase 2 update — Admin Dashboard URL configuration.

Laravel source:  routes/web.php  (lines 131–306)
Django target:   apps/admin_panel/urls.py

Laravel → Django URL mapping:
  GET  /admin/login      →  admin_login_page    (show_login_form)
  POST /admin/login      →  admin_login_post    (admin_login)
  GET  /admin/dashboard  →  admin_dashboard     (admin_dashboard)
  GET  /admin/logout     →  admin_logout        (admin_logout)

Notes:
  - All admin routes sit under the '' prefix (root URLconf includes this file directly).
  - Route names match Laravel's 'admin.' namespace convention as Django named URLs.
  - Only the four routes implemented in Phase 1 + Phase 2 are defined here.
  - Additional routes (agents, settings, finance, etc.) will be added in later phases.
  - The dashboard view performs its own session auth check; no middleware is registered
    here — per the project constraint of not creating new middleware in Phase 2.
"""

from django.urls import path
from .views.dashboard import (
    show_login_form,
    admin_login,
    admin_dashboard,
    admin_logout,
)
from .views.security import (
    threat_logs,
    delete_threat_log,
    blocked_ips,
    block_ip,
    unblock_ip,
)
from .views.agents import (
    agent_list,
    manage_agent,
    toggle_status,
    update_badge,
    save_agent_notes,
    update_visibility,
    update_achievement_limit,
    update_plan,
    toggle_review_approval,
    update_profile,
    get_agent_json,
    get_edit_logs,
    agent_approvals,
    agent_pending_registrations,
    bulk_action_agents,
)
from .views.reviews import (
    reviews_index,
    toggle_review_approval,
    bulk_approve_reviews,
    delete_review,
)
from .views.contacts import (
    contacts_index,
    contacts_show,
    contacts_update_status,
    contacts_delete,
)
from .views.geocoding import (
    index as geocoding_index,
    geocode_single,
    geocode_batch,
    stats as geocoding_stats,
)
from .views.pincode import (
    index as pincode_index,
    upload as pincode_upload,
    import_data as pincode_import,
    get_districts as pincode_districts,
    sample_download as pincode_sample,
    export_data as pincode_export,
    delete_by_state as pincode_delete_state,
)
from .views import settings, subscriptions
from .views.delete import admin_delete
from .views.distributors import (
    distributor_list,
    distributor_create,
    distributor_store,
    distributor_detail,
    toggle_distributor_status,
)
from .views.users import user_list, user_edit, user_update
from .views.events import event_list, event_show, event_export
from .views.leads import lead_list, update_lead_status
from .views.revenue import revenue_dashboard
from .views.invoices import (
    invoice_list,
    preview_invoice,
    download_invoice,
    save_sheet_url,
    sync_sheet,
    open_sheet,
)
from .views.promo_codes import (
    promo_code_list,
    toggle_promo_code_status,
    store_promo_code,
    update_promo_code,
)
from .views.free_trial import (
    free_trial_index,
    ft_update_trial_config,
    ft_update_upgrade_discount,
    ft_update_referral_config,
    ft_generate_promo,
    ft_update_promo,
    ft_toggle_promo,
    ft_delete_promo,
    ft_history,
    ft_analytics_data,
    ft_force_test_credit,
)
from .views import finance
from .views import content
from .views.referrals import (
    admin_referrals_index,
    admin_referrals_toggle_code,
    admin_referrals_mark_claimed,
    admin_referrals_generate_missing,
    admin_referrals_update_tiers,
)
from .views.agent_referral import (
    referral_join,
    agent_referral_dashboard,
)
from .views.advanced import analytics, activity_logs, delete_activity_log
from .views.export import (
    index as export_index,
    export_agents,
    export_leads,
    export_contacts,
    export_subscriptions,
    export_reviews,
    export_pending,
)
from .views.broadcast import broadcast_index, send_broadcast
from .views.notify import notify_index, notify_send, notify_broadcast

from .views.qr_files import (
    qr_files_index,
    qr_files_store,
    qr_files_update,
    qr_files_destroy,
    qr_files_download,
)
from .views.admins import (
    admins_index,
    admins_create,
    admins_store,
    admins_edit,
    admins_update,
    admins_destroy,
)
from .views.insurance import (
    insurance_index,
    insurance_create,
    insurance_store,
    insurance_show,
    insurance_toggle_status,
)
from .views.insurance_approvals import (
    insurance_approvals_index,
    insurance_approvals_process,
    insurance_approvals_approve_onboarding,
    insurance_approvals_reject_onboarding,
)
from .views.pages import (
    pages_index,
    pages_create,
    pages_store,
    pages_edit,
    pages_update,
    pages_delete,
)

# app_name = "admin_panel"

urlpatterns = [
    # GET  /admin/          — redirect to login (convenience root)
    # Maps to Laravel: Route::get('/login', ...) inside prefix('admin')
    path("admin/", show_login_form, name="admin_login"),

    # GET  /admin/login/    — show admin login form
    path("admin/login/", show_login_form, name="admin_login_page"),

    # POST /admin/login/    — process admin login credentials
    path("admin/login/post/", admin_login, name="admin_login_post"),

    # GET  /admin/dashboard/  — admin dashboard (Phase 2 — full stats)
    # Maps to Laravel: Route::get('/dashboard', [AdminDashboardController::class, 'index'])->name('dashboard')
    path("admin/dashboard/", admin_dashboard, name="admin_dashboard"),

    # GET  /admin/logout/   — destroy admin session, redirect to login
    # Maps to Laravel: Route::get('/logout', [AdminAuthController::class, 'logout'])->name('logout')
    path("admin/logout/", admin_logout, name="admin_logout"),

    # Phase 3B: Agents List
    path("admin/agents/", agent_list, name="admin_agents"),
    
    # Phase 3C: Manage Agent
    path("admin/agents/<int:id>/manage/", manage_agent, name="admin_agents_manage"),

    # Phase 4A: Agent Mutations
    path("admin/agents/toggle-status/", toggle_status, name="admin_agents_toggle_status"),
    path("admin/agents/update-badge/", update_badge, name="admin_agents_update_badge"),
    path("admin/agents/save-notes/", save_agent_notes, name="admin_agents_save_notes"),
    path("admin/agents/bulk-action/", bulk_action_agents, name="admin_agents_bulk_action"),
    path("admin/delete/", admin_delete, name="admin_agents_delete"),

    # Phase 4B: More Mutations
    path("admin/agents/update-visibility/", update_visibility, name="admin_agents_update_visibility"),
    path("admin/agents/update-achievement-limit/", update_achievement_limit, name="admin_agents_update_achievement_limit"),
    path("admin/agents/update-plan/", update_plan, name="admin_agents_update_plan"),
    path("admin/agents/toggle-review-approval/", toggle_review_approval, name="admin_agents_toggle_review_approval"),

    # Phase 4C: Manage Agent Completion
    path("admin/agents/update-profile/", update_profile, name="admin_agents_update_profile"),
    path("admin/agents/get/<int:id>/", get_agent_json, name="admin_agents_get_agent_json"),
    path("admin/agents/<int:id>/edit-logs/", get_edit_logs, name="admin_agents_get_edit_logs"),

    # Phase 4D: Queues
    path("admin/approvals/", agent_approvals, name="admin_agents_approvals"),
    path("admin/pending-registrations/", agent_pending_registrations, name="admin_agents_pending_registrations"),

    # Phase 5: Finance & Accounts
    path("admin/finance/", finance.index, name="admin_finance_index"),
    path("admin/finance/mark-payment/", finance.mark_payment, name="admin_finance_mark_payment"),

    # Phase 5: Content Manager
    path('admin/content/about/',          content.about,          name='admin_content_about'),
    path('admin/content/about/update/',   content.update_about,   name='admin_content_about_update'),
    path('admin/content/faqs/',                          content.faqs,                name='admin_content_faqs'),
    path('admin/content/faqs/settings/update/',          content.faq_settings_update, name='admin_content_faqs_settings_update'),
    path('admin/content/faqs/store/',                    content.faq_store,           name='admin_content_faqs_store'),
    path('admin/content/faqs/<int:faq_id>/update/',      content.faq_update,          name='admin_content_faqs_update'),

    path('admin/content/faqs/toggle/',                   content.faq_toggle,          name='admin_content_faqs_toggle'),
    path('admin/content/contact/',         content.contact,        name='admin_content_contact'),
    path('admin/content/contact/update/',  content.update_contact, name='admin_content_contact_update'),

    # Phase 7A: Content — Banner Slides & Plans/Pricing
    path('admin/content/banners/',         content.banners,         name='admin_content_banners'),
    path('admin/content/banners/update/',  content.update_banners,  name='admin_content_banners_update'),
    path('admin/content/plans/',           content.plans,           name='admin_content_plans'),
    path('admin/content/plans/update/',    content.update_plans,    name='admin_content_plans_update'),

    # Phase 7B: CMS Static Pages
    path('admin/pages/',                          pages_index,  name='admin_pages_index'),
    path('admin/pages/create/',                   pages_create, name='admin_pages_create'),
    path('admin/pages/store/',                    pages_store,  name='admin_pages_store'),
    path('admin/pages/<int:page_id>/edit/',        pages_edit,   name='admin_pages_edit'),
    path('admin/pages/<int:page_id>/update/',      pages_update, name='admin_pages_update'),
    path('admin/pages/<int:page_id>/delete/',      pages_delete, name='admin_pages_delete'),

    # Phase 6B: Distributors
    path("admin/distributors/", distributor_list, name="admin_distributors"),
    path("admin/distributors/create/", distributor_create, name="admin_distributors_create"),
    path("admin/distributors/store/", distributor_store, name="admin_distributors_store"),
    path("admin/distributors/toggle-status/", toggle_distributor_status, name="admin_distributor_toggle_status"),
    path("admin/distributors/<int:distributor_id>/", distributor_detail, name="admin_distributor_detail"),

    # Phase 6C: Users
    path("admin/users/", user_list, name="admin_users"),
    path("admin/users/<int:user_id>/edit/", user_edit, name="admin_users_edit"),
    path("admin/users/<int:user_id>/update/", user_update, name="admin_users_update"),

    # Phase 6D.1A: Events
    path("admin/events/", event_list, name="admin_events_index"),
    path("admin/events/<int:event_id>/", event_show, name="admin_events_show"),
    # Phase 6D.1C: Event Export
    path("admin/events/<int:event_id>/export/", event_export, name="admin_events_export"),

    # Phase 6E: Agent Leads
    path("admin/leads/", lead_list, name="admin_leads_index"),
    path("admin/leads/update-status/", update_lead_status, name="admin_leads_update_status"),

    # Phase 6F: Revenue Dashboard
    path("admin/revenue/", revenue_dashboard, name="admin_revenue"),

    # Phase 6G.1A: Invoices Dashboard
    path("admin/invoices/", invoice_list, name="admin_invoices"),
    
    # Phase 6G.2D: Preview and Download
    path("admin/invoices/<int:invoice_id>/preview/", preview_invoice, name="admin_invoice_preview"),
    path("admin/invoices/<int:invoice_id>/download/", download_invoice, name="admin_invoice_download"),

    # Phase 6G.4B: Google Sheet Sync
    path("admin/invoices/settings/url/", save_sheet_url, name="admin_invoice_save_sheet_url"),
    path("admin/invoices/sync/", sync_sheet, name="admin_invoice_sync_sheet"),
    path("admin/invoices/open-sheet/", open_sheet, name="admin_invoice_open_sheet"),

    # Phase X.1: Promo Codes
    path("admin/promo-codes/", promo_code_list, name="admin_promo_codes"),
    path("admin/promo-codes/store/", store_promo_code, name="admin_promo_code_store"),
    path("admin/promo-codes/<int:promo_id>/update/", update_promo_code, name="admin_promo_code_update"),
    path("admin/promo-codes/<int:promo_id>/toggle-status/", toggle_promo_code_status, name="admin_promo_code_toggle_status"),

    # Phase FREE_TRIAL.2: Free Trial Manager
    path("admin/free-trial/",                         free_trial_index,           name="admin_free_trial"),
    path("admin/free-trial/update-config/",           ft_update_trial_config,     name="admin_ft_update_config"),
    path("admin/free-trial/update-discount/",         ft_update_upgrade_discount, name="admin_ft_update_discount"),
    path("admin/free-trial/update-referral-config/",  ft_update_referral_config,  name="admin_ft_update_referral_config"),
    path("admin/free-trial/test-credit/",             ft_force_test_credit,       name="admin_ft_force_test_credit"),
    path("admin/free-trial/generate-promo/",          ft_generate_promo,          name="admin_ft_generate_promo"),
    path("admin/free-trial/promo/<int:promo_id>/update/", ft_update_promo,         name="admin_ft_update_promo"),
    path("admin/free-trial/toggle-promo/",            ft_toggle_promo,            name="admin_ft_toggle_promo"),
    path("admin/free-trial/promo/<int:promo_id>/delete/", ft_delete_promo,         name="admin_ft_delete_promo"),
    path("admin/free-trial/history/",                 ft_history,                 name="admin_ft_history"),
    path("admin/free-trial/analytics-data/",          ft_analytics_data,          name="admin_ft_analytics_data"),

    # Phase REFERRAL_SYSTEM: Admin Referral Analytics
    path("admin/referrals/",                            admin_referrals_index,           name="admin_referrals_index"),
    path("admin/referrals/toggle-code/",                admin_referrals_toggle_code,     name="admin_referrals_toggle_code"),
    path("admin/referrals/<int:code_id>/mark-claimed/", admin_referrals_mark_claimed,    name="admin_referrals_mark_claimed"),
    path("admin/referrals/generate-missing-codes/",    admin_referrals_generate_missing, name="admin_referrals_generate_missing"),
    path("admin/referrals/update-tiers/",              admin_referrals_update_tiers,    name="admin_referrals_update_tiers"),

    # Phase REFERRAL_SYSTEM: Agent-facing
    path("join/<str:ref_code>/",   referral_join,              name="referral_join"),
    path("agent/referral/",        agent_referral_dashboard,   name="agent_referral_dashboard"),

    # Phase REVIEWS: Reviews Management
    path("admin/reviews/",                reviews_index,          name="admin_reviews_index"),
    path("admin/reviews/toggle-approval/", toggle_review_approval, name="admin_reviews_toggle_approval"),
    path("admin/reviews/bulk-approve/",   bulk_approve_reviews,   name="admin_reviews_bulk_approve"),
    path("admin/reviews/delete/",         delete_review,          name="admin_reviews_delete"),

    # Phase CONTACT_INBOX: Contact Submissions Management
    path("admin/contacts/",                       contacts_index,         name="admin_contacts_index"),
    path("admin/contacts/<int:submission_id>/",   contacts_show,          name="admin_contacts_show"),
    path("admin/contacts/update-status/",         contacts_update_status, name="admin_contacts_update_status"),
    path("admin/contacts/delete/",                contacts_delete,        name="admin_contacts_delete"),

    # Phase GEOCODING: Geocoding Manager
    path("admin/geocoding-manager/",               geocoding_index,  name="admin_geocoding_index"),
    path("admin/geocoding-manager/single/",        geocode_single,   name="admin_geocoding_single"),
    path("admin/geocoding-manager/batch/",         geocode_batch,    name="admin_geocoding_batch"),
    path("admin/geocoding-manager/stats/",         geocoding_stats,  name="admin_geocoding_stats"),

    # Phase PINCODE: Pincode Manager
    path("admin/pincode-manager/",                pincode_index,             name="admin_pincode_index"),
    path("admin/pincode-manager/upload/",         pincode_upload,            name="admin_pincode_upload"),
    path("admin/pincode-manager/import/",         pincode_import,            name="admin_pincode_import"),
    path("admin/pincode-manager/districts/",      pincode_districts,         name="admin_pincode_districts"),
    path("admin/pincode-manager/sample/",         pincode_sample,            name="admin_pincode_sample"),
    path("admin/pincode-manager/export/",         pincode_export,            name="admin_pincode_export"),
    path("admin/pincode-manager/delete-state/",   pincode_delete_state,      name="admin_pincode_delete_state"),

    # Phase SETTINGS: Settings & Homepage Editor
    path("admin/settings/general/",         settings.general,             name="admin_settings_general"),
    path("admin/settings/seo/",             settings.seo,                 name="admin_settings_seo"),
    path("admin/settings/security/",        settings.security,            name="admin_settings_security"),
    path("admin/settings/templates/",       settings.templates,           name="admin_settings_templates"),
    path("admin/settings/templates/update/",settings.update_templates,    name="admin_settings_templates_update"),
    path("admin/settings/update/",          settings.update_settings,     name="admin_settings_update"),
    path("admin/settings/homepage/",        settings.homepage,            name="admin_settings_homepage"),
    path("admin/settings/homepage/update/", settings.update_homepage,     name="admin_settings_homepage_update"),
    path("admin/settings/hero-section/",    settings.hero_section,        name="admin_settings_hero_section"),
    path("admin/settings/hero-section/update/", settings.update_hero_section, name="admin_settings_hero_section_update"),

    # Phase SUBSCRIPTIONS
    path("admin/subscriptions/",            subscriptions.subscriptions_index, name="admin_subscriptions_index"),
    path("admin/subscriptions/delete/",     subscriptions.delete_subscription, name="admin_delete_subscription"),

    # Phase ADVANCED_ANALYTICS
    path("admin/advanced/analytics/",       analytics,                 name="advanced_analytics"),
    path("admin/advanced/activity-logs/",   activity_logs,             name="advanced_activity_logs"),
    path("admin/advanced/activity-logs/delete/", delete_activity_log,  name="advanced_activity_logs_delete"),

    # Phase EXPORT_CENTER
    path("admin/export/",                   export_index,              name="export_index"),
    path("admin/export/agents/",            export_agents,             name="export_agents"),
    path("admin/export/leads/",             export_leads,              name="export_leads"),
    path("admin/export/contacts/",          export_contacts,           name="export_contacts"),
    path("admin/export/subscriptions/",     export_subscriptions,      name="export_subscriptions"),
    path("admin/export/reviews/",           export_reviews,            name="export_reviews"),
    path("admin/export/pending/",           export_pending,            name="export_pending"),

    # Phase BROADCASTS
    path("admin/broadcast/",                broadcast_index,           name="broadcast_index"),
    path("admin/broadcast/send/",           send_broadcast,            name="broadcast_send"),

    # Phase AGENT_PUSH_NOTIFICATIONS
    path("admin/agent/notifications/",             notify_index,              name="agent_notify"),
    path("admin/agent/notifications/send/",        notify_send,               name="agent_notify_send"),
    path("admin/agent/notifications/broadcast/",   notify_broadcast,          name="agent_notify_broadcast"),

    # Phase SECURITY
    path("admin/security/threat-logs/",                 threat_logs,        name="security_threat_logs"),
    path("admin/security/threat-logs/delete/",          delete_threat_log,  name="security_threat_logs_delete"),
    path("admin/security/blocked-ips/",                 blocked_ips,        name="security_blocked_ips"),
    path("admin/security/block-ip/",                    block_ip,           name="security_block_ip"),
    path("admin/security/blocked-ips/<int:ip_id>/unblock/", unblock_ip,     name="security_unblock_ip"),

    # QR Code Generator & File Manager
    path("admin/qr-files/", qr_files_index, name="admin_qr_files_index"),
    path("admin/qr-files/upload/", qr_files_store, name="admin_qr_files_store"),
    path("admin/qr-files/<int:id>/update/", qr_files_update, name="admin_qr_files_update"),
    path("admin/qr-files/<int:id>/delete/", qr_files_destroy, name="admin_qr_files_delete"),
    path("d/<str:code>/", qr_files_download, name="qr_download"),

    # Staff Admin Management
    path("admin/admins/", admins_index, name="admin_admins_index"),
    path("admin/admins/create/", admins_create, name="admin_admins_create"),
    path("admin/admins/store/", admins_store, name="admin_admins_store"),
    path("admin/admins/<int:id>/edit/", admins_edit, name="admin_admins_edit"),
    path("admin/admins/<int:id>/update/", admins_update, name="admin_admins_update"),
    path("admin/admins/<int:id>/delete/", admins_destroy, name="admin_admins_delete"),

    # Insurance Companies
    path("admin/insurance/", insurance_index, name="admin_insurance_index"),
    path("admin/insurance/create/", insurance_create, name="admin_insurance_create"),
    path("admin/insurance/store/", insurance_store, name="admin_insurance_store"),
    path("admin/insurance/<int:id>/", insurance_show, name="admin_insurance_show"),
    path("admin/insurance/toggle-status/", insurance_toggle_status, name="admin_insurance_toggle_status"),

    # Insurance Onboarding & Approvals
    path("admin/insurance-approvals/", insurance_approvals_index, name="admin_insurance_approvals_index"),
    path("admin/insurance-approvals/<int:id>/process/", insurance_approvals_process, name="admin_insurance_approvals_process"),
    path("admin/insurance-approvals/onboarding/<int:id>/approve/", insurance_approvals_approve_onboarding, name="admin_insurance_approvals_approve_onboarding"),
    path("admin/insurance-approvals/onboarding/<int:id>/reject/", insurance_approvals_reject_onboarding, name="admin_insurance_approvals_reject_onboarding"),
]
