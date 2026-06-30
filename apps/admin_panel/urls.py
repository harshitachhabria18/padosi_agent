from django.urls import path
from .views import content, settings, auth, dashboard, advanced, agents, reviews, subscriptions, broadcast, contacts, notify, security, pincode, geocoding, export, finance, pages

app_name = 'admin_panel'

urlpatterns = [
    # Dashboard
    path('dashboard/',              dashboard.admin_dashboard, name='dashboard'),

    # Agents
    path('agents/',                 agents.agent_list,   name='agent_list'),
    
    # Reviews
    path('reviews/',                reviews.reviews_index,          name='reviews_index'),
    path('reviews/toggle-approval/', reviews.toggle_review_approval, name='reviews_toggle_approval'),
    path('reviews/bulk-approve/',   reviews.bulk_approve_reviews,   name='reviews_bulk_approve'),
    path('reviews/delete/',         reviews.delete_review,          name='reviews_delete'),
    
    # Subscriptions
    path('subscriptions/',          subscriptions.subscriptions_index, name='subscriptions'),
    path('subscriptions/delete/',    subscriptions.delete_subscription,  name='subscriptions_delete'),
    
    # Broadcasts
    path('broadcast/',              broadcast.broadcast_index,      name='broadcast_index'),
    path('broadcast/send/',         broadcast.send_broadcast,       name='broadcast_send'),

    # Contact Inbox
    path('contacts/',                       contacts.contacts_index,         name='contacts_index'),
    path('contacts/<int:submission_id>/',   contacts.contacts_show,          name='contacts_show'),
    path('contacts/update-status/',         contacts.contacts_update_status,  name='contacts_update_status'),
    path('contacts/delete/',                contacts.contacts_delete,         name='contacts_delete'),

    # Agent Push Notifications
    path('agent/notify/',                   notify.notify_index,              name='agent_notify'),
    path('agent/notify/send/',              notify.notify_send,               name='agent_notify_send'),
    path('agent/notify/broadcast/',         notify.notify_broadcast,          name='agent_notify_broadcast'),

    # Advanced / Analytics
    path('advanced/analytics/',     advanced.analytics,        name='advanced_analytics'),
    path('advanced/activity-logs/', advanced.activity_logs,    name='advanced_activity_logs'),
    path('advanced/activity-logs/delete/', advanced.delete_activity_log, name='advanced_activity_logs_delete'),

    # Security Threat Intelligence & Blocked IPs
    path('security/threat-logs/', security.threat_logs, name='security_threat_logs'),
    path('security/threat-logs/delete/', security.delete_threat_log, name='security_threat_logs_delete'),
    path('security/blocked-ips/', security.blocked_ips, name='security_blocked_ips'),
    path('security/block-ip/', security.block_ip, name='security_block_ip'),
    path('security/blocked-ips/<int:ip_id>/unblock/', security.unblock_ip, name='security_unblock_ip'),

    # Auth
    path('login/',                  auth.admin_login,       name='login'),
    path('logout/',                 auth.admin_logout,      name='logout'),

    # About
    path('content/about/',          content.about,          name='content_about'),
    path('content/about/update/',   content.update_about,   name='content_about_update'),

    # FAQs
    path('content/faqs/',                          content.faqs,                name='content_faqs'),
    path('content/faqs/settings/update/',          content.faq_settings_update, name='content_faqs_settings_update'),
    path('content/faqs/store/',                    content.faq_store,           name='content_faqs_store'),
    path('content/faqs/<int:faq_id>/update/',      content.faq_update,          name='content_faqs_update'),
    path('content/faqs/<int:faq_id>/delete/',      content.faq_delete,          name='content_faqs_delete'),
    path('content/faqs/toggle/',                   content.faq_toggle,          name='content_faqs_toggle'),

    # Contact
    path('content/contact/',         content.contact,        name='content_contact'),
    path('content/contact/update/',  content.update_contact, name='content_contact_update'),

    # Banners
    path('content/banners/',         content.banners,        name='content_banners'),
    path('content/banners/update/',  content.update_banners, name='content_banners_update'),

    # Plans & Pricing
    path('content/plans/',           content.plans,          name='content_plans'),
    path('content/plans/update/',    content.update_plans,   name='content_plans_update'),

    # Pages & CMS
    path('pages/',                   pages.index,             name='pages_index'),
    path('pages/create/',            pages.create,            name='pages_create'),
    path('pages/store/',             pages.store,             name='pages_store'),
    path('pages/<int:page_id>/edit/',pages.edit,              name='pages_edit'),
    path('pages/<int:page_id>/update/',pages.update,          name='pages_update'),
    path('pages/<int:page_id>/delete/',pages.delete,          name='pages_delete'),

    # Settings & Homepage Editor
    path('settings/general/',         settings.general,             name='settings_general'),
    path('settings/seo/',             settings.seo,                 name='settings_seo'),
    path('settings/security/',        settings.security,            name='settings_security'),
    path('settings/templates/',       settings.templates,           name='settings_templates'),
    path('settings/templates/update/',settings.update_templates,    name='settings_templates_update'),
    path('settings/update/',          settings.update_settings,     name='settings_update'),
    path('settings/homepage/',        settings.homepage,            name='settings_homepage'),
    path('settings/homepage/update/', settings.update_homepage,     name='settings_homepage_update'),
    path('settings/hero-section/',    settings.hero_section,        name='settings_hero_section'),
    path('settings/hero-section/update/', settings.update_hero_section, name='settings_hero_section_update'),

    # Pincode Manager
    path('pincode/',                pincode.index,             name='pincode_index'),
    path('pincode/upload/',         pincode.upload,            name='pincode_upload'),
    path('pincode/import/',         pincode.import_data,       name='pincode_import'),
    path('pincode/districts/',      pincode.get_districts,     name='pincode_districts'),
    path('pincode/sample/',         pincode.sample_download,   name='pincode_sample'),
    path('pincode/export/',         pincode.export_data,       name='pincode_export'),
    path('pincode/delete-state/',   pincode.delete_by_state,   name='pincode_delete_state'),

    # Geocoding Manager
    path('geocoding-manager/',             geocoding.index,           name='geocoding_index'),
    path('geocoding-manager/single/',      geocoding.geocode_single,  name='geocoding_single'),
    path('geocoding-manager/batch/',       geocoding.geocode_batch,   name='geocoding_batch'),
    path('geocoding-manager/stats/',       geocoding.stats,           name='geocoding_stats'),

    # Export Center
    path('export/',                        export.index,              name='export_index'),
    path('export/agents/',                 export.export_agents,      name='export_agents'),
    path('export/leads/',                  export.export_leads,       name='export_leads'),
    path('export/contacts/',               export.export_contacts,    name='export_contacts'),
    path('export/subscriptions/',          export.export_subscriptions, name='export_subscriptions'),
    path('export/reviews/',                export.export_reviews,     name='export_reviews'),
    path('export/pending/',                export.export_pending,     name='export_pending'),

    # Finance & Accounts
    path('finance/',               finance.index,        name='finance_index'),
    path('finance/mark-payment/',  finance.mark_payment, name='finance_mark_payment'),
]
