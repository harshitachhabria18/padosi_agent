"""
Agent Registration Views — session-driven multi-step registration.

Flow:
  1. GET  /agent-registration/     → renders the page (OTP → Step1 → Step2)
  2. POST /agent-send-otp/         → generates OTP, sends via Brevo, stores in session
  3. POST /agent-verify-otp/       → verifies OTP, marks email verified in session
  4. POST /agent-register-step1/   → saves basic info to AgentDraft, advances to step 2
  5. POST /agent-register-step2/   → saves profile details, redirects to plans
"""

import json
import os
import random
import time
import logging
import re
from decimal import Decimal, ROUND_HALF_UP

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.utils import timezone
from django.conf import settings

from apps.agents.models import Agent, AgentDraft, PromoCode, RegistrationActivityLog
from apps.home.models import SiteSetting
from apps.home.models.pincode import Pincode
from apps.agents.services.brevo import send_otp_email
from apps.agents.services.feature_unlock import (
    PLAN_LABELS,
    paid_plan_label,
    resolve_checkout_plan_slug,
    plan_slug_from_name,
)
from apps.agents.services.post_payment import queue_invoice_and_welcome
from apps.agents.services.razorpay_checkout import (
    MOCK_SIGNATURE,
    checkout_payload,
    create_checkout_order,
    gateway_failure_message,
    is_mock_payment,
    login_agent_user,
    mock_payment_id,
    razorpay_client,
)

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────────
OTP_EXPIRY_SECONDS = 600  # 10 minutes
ALL_INDIAN_STATES = [
    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
    'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand',
    'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur',
    'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Punjab',
    'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura',
    'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
    'Andaman and Nicobar Islands', 'Chandigarh',
    'Dadra and Nagar Haveli and Daman and Diu',
    'Delhi', 'Jammu and Kashmir', 'Ladakh', 'Lakshadweep', 'Puducherry',
]

INSURANCE_SEGMENTS = [
    {'id': 'health', 'label': 'Health',  'icon': 'fas fa-heartbeat'},
    {'id': 'life',   'label': 'Life',    'icon': 'fas fa-user-shield'},
    {'id': 'motor',  'label': 'Motor',   'icon': 'fas fa-car'},
    {'id': 'sme',    'label': 'SME',     'icon': 'fas fa-building'},
]

LANGUAGE_OPTIONS = [
    'Hindi', 'English', 'Gujarati', 'Marathi', 'Tamil',
    'Telugu', 'Kannada', 'Bengali', 'Punjabi', 'Malayalam',
    'Odia', 'Urdu', 'Assamese', 'Rajasthani',
]

_DEFAULT_PRICING = {
    'scratch_card_enabled': True,
    'social_discount_active': True,
    'social_discount_amount': 200,
    'starter': {
        'name': PLAN_LABELS['starter'],
        'full_price': 1999,
        'promo_price': 1499,
        'scratch_price': 1299,
        'description': 'Perfect for New Agents',
        'badge': 'STANDARD',
        'scratch_text': 'SCRATCH',
        'scratch_enabled': True,
    },
    'professional': {
        'name': PLAN_LABELS['professional'],
        'full_price': 9999,
        'promo_price': 7999,
        'scratch_price': 7799,
        'description': 'For Established Professionals',
        'badge': 'RECOMMENDED',
        'scratch_text': 'SCRATCH',
        'scratch_enabled': True,
    },
    'promo_discount_label': 'Partner Promo Applied! Once in a lifetime offer!',
    'standard_label': 'Get started with our standard partner plans',
    'choose_plan_heading': 'Start your digital journey',
    'comparison_price_display': 'original',
    'social_links': [
        {'platform': 'Instagram', 'url': 'https://instagram.com/padosiagent', 'icon': 'fa-instagram'},
        {'platform': 'Facebook', 'url': 'https://facebook.com/padosiagent', 'icon': 'fa-facebook'},
        {'platform': 'YouTube', 'url': 'https://youtube.com/@padosiagent', 'icon': 'fa-youtube'},
        {'platform': 'LinkedIn', 'url': 'https://linkedin.com/company/padosiagent', 'icon': 'fa-linkedin'},
    ],
    'follow_tiers': [
        {'follows': 1, 'discount_amount': 100, 'starter_discount': 100, 'prof_discount': 100, 'starter_price': 1399, 'prof_price': 7899},
        {'follows': 2, 'discount_amount': 200, 'starter_discount': 200, 'prof_discount': 200, 'starter_price': 1299, 'prof_price': 7799},
        {'follows': 3, 'discount_amount': 300, 'starter_discount': 300, 'prof_discount': 300, 'starter_price': 1199, 'prof_price': 7699},
        {'follows': 4, 'discount_amount': 500, 'starter_discount': 500, 'prof_discount': 500, 'starter_price': 999, 'prof_price': 7499},
    ],
}

_STARTER_PLAN_UI_FEATURES = [
    {'name': 'Permanent<br>Webpage', 'icon': 'fa-globe', 'color': '#16a34a', 'bg_color': '#f0fdf4'},
    {'name': 'Professional<br>Digital Card', 'icon': 'fa-id-card-clip', 'color': '#6d28d9', 'bg_color': '#f3e8ff'},
    {'name': 'Licensed<br>Badge', 'icon': 'fa-shield-halved', 'color': '#f59e0b', 'bg_color': '#fffbeb'},
    {'name': 'Call & WhatsApp<br>Buttons', 'icon': 'fa-phone', 'color': '#16a34a', 'bg_color': '#f0fdf4'},
    {'name': 'Customer Review<br>& Rating', 'icon': 'fa-star', 'color': '#6d28d9', 'bg_color': '#f3e8ff'},
    {'name': 'Profile<br>QR', 'icon': 'fa-qrcode', 'color': '#3b82f6', 'bg_color': '#eff6ff'},
    {'name': 'Review & Rating<br>QR', 'icon': 'fa-comment-dots', 'color': '#0d9488', 'bg_color': '#f0fdfa'},
    {'name': 'Product<br>Showcase', 'icon': 'fa-store', 'color': '#3b82f6', 'bg_color': '#eff6ff'},
    {'name': 'Visibility in Your<br>Pin Code', 'icon': 'fa-location-dot', 'color': '#e11d48', 'bg_color': '#fff1f2'},
    {'name': 'Downloadable<br>Digital Card', 'icon': 'fa-download', 'color': '#6366f1', 'bg_color': '#eef2ff'},
    {'name': 'New Business<br>Leads', 'icon': 'fa-user-plus', 'color': '#16a34a', 'bg_color': '#f0fdf4'},
]

_PROFESSIONAL_PLAN_UI_FEATURES = [
    {'name': 'Trusted<br>Badge', 'icon': 'fa-award', 'color': '#f59e0b', 'bg_color': '#fffbeb'},
    {'name': 'Lead<br>Preferences', 'icon': 'fa-filter', 'color': '#6366f1', 'bg_color': '#eef2ff'},
    {'name': 'SEO - Google<br>will know you', 'icon': 'fa-magnifying-glass', 'color': '#3b82f6', 'bg_color': '#eff6ff'},
    {'name': 'AIO &<br>GEO', 'icon': 'fa-robot', 'color': '#6d28d9', 'bg_color': '#f3e8ff'},
    {'name': 'Profile<br>Analytics', 'icon': 'fa-chart-column', 'color': '#0d9488', 'bg_color': '#f0fdfa'},
    {'name': 'Gallery', 'icon': 'fa-images', 'color': '#e11d48', 'bg_color': '#fff1f2'},
    {'name': 'AI Auto-fill &<br>Suggestions', 'icon': 'fa-wand-magic-sparkles', 'color': '#8b5cf6', 'bg_color': '#f5f3ff'},
]

_PLAN_COMPARISON_ROWS = [
    {'name': 'Permanent Webpage', 'starter': True, 'professional': True},
    {'name': 'Professional Digital Card', 'starter': True, 'professional': True},
    {'name': 'Licensed Badge', 'starter': True, 'professional': True},
    {'name': 'Call & WhatsApp Buttons', 'starter': True, 'professional': True},
    {'name': 'Customer Review & Rating', 'starter': True, 'professional': True},
    {'name': 'Profile QR', 'starter': True, 'professional': True},
    {'name': 'Review & Rating QR', 'starter': True, 'professional': True},
    {'name': 'Product Showcase', 'starter': True, 'professional': True},
    {'name': 'Visibility in Your Pin Code', 'starter': True, 'professional': True},
    {'name': 'Downloadable Digital Card', 'starter': True, 'professional': True},
    {'name': 'New Business Leads', 'starter': True, 'professional': 'priority'},
    {'name': 'Trusted Badge', 'starter': False, 'professional': True},
    {'name': 'Lead Preferences', 'starter': False, 'professional': True},
    {'name': 'SEO – Google will know you', 'starter': False, 'professional': True},
    {'name': 'AIO & GEO', 'starter': False, 'professional': True},
    {'name': 'Profile Analytics', 'starter': False, 'professional': True},
    {'name': 'Gallery', 'starter': False, 'professional': True},
    {'name': 'AI Auto-fill & Suggestions', 'starter': False, 'professional': True},
]

_DEFAULT_SCRATCH_POPUP = {
    'overlay_bg': 'rgba(15, 23, 42, 0.85)',
    'overlay_blur_px': 4,
    'modal_bg': '#ffffff',
    'modal_border_color': '#7c3aed',
    'modal_border_width_px': 3,
    'modal_radius_px': 28,
    'modal_shadow': '0 18px 50px rgba(88, 28, 135, 0.22)',
    'close_btn_bg': '#f1f5f9',
    'close_btn_color': '#64748b',
    'close_btn_hover_bg': '#e2e8f0',
    'close_btn_hover_color': '#0f172a',
    'urgency_line_1': '🔥 Hurry! Offer valid only for the first {total_seats} users!',
    'urgency_line_2': '🔥 {claimed_seats}/{total_seats} Claimed',
    'urgency_top_color': '#9f1239',
    'urgency_count_color': '#e11d48',
    'total_seats': 1000,
    'claimed_seats': 874,
    'strike_price_color': '#94a3b8',
    'current_price_color': '#16a34a',
    'discount_sticker_bg': '#e11d48',
    'discount_label': 'OFF',
    'follower_discount_text': 'Extra Follower Discount Applied!',
    'follower_discount_bg': '#d1fae5',
    'follower_discount_color': '#059669',
    'follower_discount_border': '#6ee7b7',
    'show_follower_discount_badge': True,
    'features_section_title': "What You'll Get",
    'features_section_accent': '#8b5cf6',
    'features_section_line': '#7c3aed',
    'social_section_title': 'Follow on',
    'show_features_section': True,
    'show_social_section': True,
    'claim_btn_text': 'Claim Offer',
    'claim_btn_bg': '#6d28d9',
    'claim_btn_color': '#ffffff',
    'claim_btn_hover_bg': '#5b21b6',
    'features': [
        {'name': 'Permanent<br>Website', 'icon': 'fa-globe', 'color': '#16a34a', 'bg_color': '#f0fdf4'},
        {'name': 'Digital<br>Card', 'icon': 'fa-id-card-clip', 'color': '#6d28d9', 'bg_color': '#f3e8ff'},
        {'name': 'Licensed<br>Badge', 'icon': 'fa-shield-halved', 'color': '#f97316', 'bg_color': '#fff7ed'},
        {'name': 'Call &<br>WhatsApp', 'icon': 'fa-phone', 'color': '#16a34a', 'bg_color': '#f0fdf4'},
        {'name': 'Customer<br>Reviews', 'icon': 'fa-star', 'color': '#6d28d9', 'bg_color': '#f3e8ff'},
        {'name': 'Product<br>Showcase', 'icon': 'fa-store', 'color': '#3b82f6', 'bg_color': '#eff6ff'},
    ],
}


def _normalize_scratch_popup(raw=None, *, format_urgency=True):
    """Merge admin scratch-popup config with defaults for choose-plan gift modal."""
    cfg = dict(_DEFAULT_SCRATCH_POPUP)
    if isinstance(raw, dict):
        for key, val in raw.items():
            if key == 'features':
                continue
            if val is not None and val != '':
                cfg[key] = val

    features = None
    if isinstance(raw, dict) and isinstance(raw.get('features'), list) and raw['features']:
        features = raw['features']
    cfg['features'] = features or list(_DEFAULT_SCRATCH_POPUP['features'])

    try:
        total_seats = int(cfg.get('total_seats') or 1000)
    except (TypeError, ValueError):
        total_seats = 1000
    try:
        claimed_seats = int(cfg.get('claimed_seats') or 874)
    except (TypeError, ValueError):
        claimed_seats = 874
    spots_left = max(0, total_seats - claimed_seats)
    cfg['total_seats'] = total_seats
    cfg['claimed_seats'] = claimed_seats
    cfg['spots_left'] = spots_left

    cfg['show_features_section'] = _parse_json_flag(cfg.get('show_features_section', True))
    cfg['show_social_section'] = _parse_json_flag(cfg.get('show_social_section', True))
    cfg['show_follower_discount_badge'] = _parse_json_flag(cfg.get('show_follower_discount_badge', True))

    if format_urgency:
        def _fmt(template, fallback):
            text = template or fallback
            try:
                return text.format(
                    total_seats=total_seats,
                    claimed_seats=claimed_seats,
                    spots_left=spots_left,
                )
            except (KeyError, ValueError, IndexError):
                return text

        cfg['urgency_line_1_display'] = _fmt(
            cfg.get('urgency_line_1'),
            _DEFAULT_SCRATCH_POPUP['urgency_line_1'],
        )
        cfg['urgency_line_2_display'] = _fmt(
            cfg.get('urgency_line_2'),
            _DEFAULT_SCRATCH_POPUP['urgency_line_2'],
        )
    else:
        cfg['urgency_line_1_display'] = cfg.get('urgency_line_1') or _DEFAULT_SCRATCH_POPUP['urgency_line_1']
        cfg['urgency_line_2_display'] = cfg.get('urgency_line_2') or _DEFAULT_SCRATCH_POPUP['urgency_line_2']

    return cfg


def _parse_scratch_popup_from_post(post):
    """Build scratch_popup dict from admin plans form POST."""
    pf_names = post.getlist('sp_feature_name[]')
    pf_icons = post.getlist('sp_feature_icon[]')
    pf_colors = post.getlist('sp_feature_color[]')
    pf_bg_colors = post.getlist('sp_feature_bg_color[]')
    features = []
    for i, name in enumerate(pf_names):
        name = (name or '').strip()
        if not name:
            continue
        features.append({
            'name': name,
            'icon': (pf_icons[i] if i < len(pf_icons) else 'fa-star').strip() or 'fa-star',
            'color': (pf_colors[i] if i < len(pf_colors) else '#16a34a').strip() or '#16a34a',
            'bg_color': (pf_bg_colors[i] if i < len(pf_bg_colors) else '#f0fdf4').strip() or '#f0fdf4',
        })

    def _int(key, default):
        try:
            return int(post.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    return {
        'overlay_bg': (post.get('sp_overlay_bg') or _DEFAULT_SCRATCH_POPUP['overlay_bg']).strip(),
        'overlay_blur_px': _int('sp_overlay_blur_px', _DEFAULT_SCRATCH_POPUP['overlay_blur_px']),
        'modal_bg': (post.get('sp_modal_bg') or _DEFAULT_SCRATCH_POPUP['modal_bg']).strip(),
        'modal_border_color': (post.get('sp_modal_border_color') or _DEFAULT_SCRATCH_POPUP['modal_border_color']).strip(),
        'modal_border_width_px': _int('sp_modal_border_width_px', _DEFAULT_SCRATCH_POPUP['modal_border_width_px']),
        'modal_radius_px': _int('sp_modal_radius_px', _DEFAULT_SCRATCH_POPUP['modal_radius_px']),
        'modal_shadow': (post.get('sp_modal_shadow') or _DEFAULT_SCRATCH_POPUP['modal_shadow']).strip(),
        'close_btn_bg': (post.get('sp_close_btn_bg') or _DEFAULT_SCRATCH_POPUP['close_btn_bg']).strip(),
        'close_btn_color': (post.get('sp_close_btn_color') or _DEFAULT_SCRATCH_POPUP['close_btn_color']).strip(),
        'close_btn_hover_bg': (post.get('sp_close_btn_hover_bg') or _DEFAULT_SCRATCH_POPUP['close_btn_hover_bg']).strip(),
        'close_btn_hover_color': (post.get('sp_close_btn_hover_color') or _DEFAULT_SCRATCH_POPUP['close_btn_hover_color']).strip(),
        'urgency_line_1': (post.get('sp_urgency_line_1') or _DEFAULT_SCRATCH_POPUP['urgency_line_1']).strip(),
        'urgency_line_2': (post.get('sp_urgency_line_2') or _DEFAULT_SCRATCH_POPUP['urgency_line_2']).strip(),
        'urgency_top_color': (post.get('sp_urgency_top_color') or _DEFAULT_SCRATCH_POPUP['urgency_top_color']).strip(),
        'urgency_count_color': (post.get('sp_urgency_count_color') or _DEFAULT_SCRATCH_POPUP['urgency_count_color']).strip(),
        'total_seats': _int('sp_total_seats', _DEFAULT_SCRATCH_POPUP['total_seats']),
        'claimed_seats': _int('sp_claimed_seats', _DEFAULT_SCRATCH_POPUP['claimed_seats']),
        'strike_price_color': (post.get('sp_strike_price_color') or _DEFAULT_SCRATCH_POPUP['strike_price_color']).strip(),
        'current_price_color': (post.get('sp_current_price_color') or _DEFAULT_SCRATCH_POPUP['current_price_color']).strip(),
        'discount_sticker_bg': (post.get('sp_discount_sticker_bg') or _DEFAULT_SCRATCH_POPUP['discount_sticker_bg']).strip(),
        'discount_label': (post.get('sp_discount_label') or _DEFAULT_SCRATCH_POPUP['discount_label']).strip()[:12] or 'OFF',
        'follower_discount_text': (post.get('sp_follower_discount_text') or _DEFAULT_SCRATCH_POPUP['follower_discount_text']).strip(),
        'follower_discount_bg': (post.get('sp_follower_discount_bg') or _DEFAULT_SCRATCH_POPUP['follower_discount_bg']).strip(),
        'follower_discount_color': (post.get('sp_follower_discount_color') or _DEFAULT_SCRATCH_POPUP['follower_discount_color']).strip(),
        'follower_discount_border': (post.get('sp_follower_discount_border') or _DEFAULT_SCRATCH_POPUP['follower_discount_border']).strip(),
        'show_follower_discount_badge': 'sp_show_follower_discount_badge' in post,
        'features_section_title': (post.get('sp_features_section_title') or _DEFAULT_SCRATCH_POPUP['features_section_title']).strip(),
        'features_section_accent': (post.get('sp_features_section_accent') or _DEFAULT_SCRATCH_POPUP['features_section_accent']).strip(),
        'features_section_line': (post.get('sp_features_section_line') or _DEFAULT_SCRATCH_POPUP['features_section_line']).strip(),
        'social_section_title': (post.get('sp_social_section_title') or _DEFAULT_SCRATCH_POPUP['social_section_title']).strip(),
        'show_features_section': 'sp_show_features_section' in post,
        'show_social_section': 'sp_show_social_section' in post,
        'claim_btn_text': (post.get('sp_claim_btn_text') or _DEFAULT_SCRATCH_POPUP['claim_btn_text']).strip()[:40] or 'Claim Offer',
        'claim_btn_bg': (post.get('sp_claim_btn_bg') or _DEFAULT_SCRATCH_POPUP['claim_btn_bg']).strip(),
        'claim_btn_color': (post.get('sp_claim_btn_color') or _DEFAULT_SCRATCH_POPUP['claim_btn_color']).strip(),
        'claim_btn_hover_bg': (post.get('sp_claim_btn_hover_bg') or _DEFAULT_SCRATCH_POPUP['claim_btn_hover_bg']).strip(),
        'features': features or list(_DEFAULT_SCRATCH_POPUP['features']),
    }

def _tier_optional_float(tier, key):
    """Return a float from a tier field, or None if missing/blank."""
    if not isinstance(tier, dict) or key not in tier:
        return None
    val = tier.get(key)
    if val in (None, ''):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _tier_plan_discount(tier, plan_key, default_discount=0):
    """Extra ₹ OFF for starter or professional. Per-plan fields win over shared discount_amount."""
    specific_key = 'starter_discount' if plan_key == 'starter' else 'prof_discount'
    specific = _tier_optional_float(tier, specific_key)
    if specific is not None:
        return specific
    shared = _tier_optional_float(tier, 'discount_amount')
    if shared is not None:
        return shared
    try:
        return float(default_discount or 0)
    except (TypeError, ValueError):
        return 0.0


def _tier_plan_charged_price(tier, plan_key, initial_price, default_discount=0):
    """Price charged for a plan at this follow tier (excl. GST)."""
    price_key = 'starter_price' if plan_key == 'starter' else 'prof_price'
    saved = _tier_optional_float(tier, price_key)
    if saved is not None and saved > 0:
        return saved
    try:
        initial = float(initial_price or 0)
    except (TypeError, ValueError):
        initial = 0.0
    return max(0.0, initial - _tier_plan_discount(tier, plan_key, default_discount))


def _get_tier_prices(pricing_config, follow_count):
    """Compute tier pricing and discounts based on the number of accounts followed."""
    if not isinstance(pricing_config, dict):
        pricing_config = dict(_DEFAULT_PRICING)

    starter_cfg = pricing_config.get('starter', _DEFAULT_PRICING['starter'])
    prof_cfg = pricing_config.get('professional', _DEFAULT_PRICING['professional'])

    starter_full = float(starter_cfg.get('full_price', 1999) or 1999)
    starter_promo = float(starter_cfg.get('promo_price', 1499) or 1499)
    starter_scratch = float(starter_cfg.get('scratch_price', starter_promo) or starter_promo)
    starter_scratch_enabled = _is_scratch_enabled(starter_cfg)

    prof_full = float(prof_cfg.get('full_price', 9999) or 9999)
    prof_promo = float(prof_cfg.get('promo_price', 7999) or 7999)
    prof_scratch = float(prof_cfg.get('scratch_price', prof_promo) or prof_promo)
    prof_scratch_enabled = _is_scratch_enabled(prof_cfg)

    starter_initial = starter_scratch if starter_scratch_enabled else starter_promo
    prof_initial = prof_scratch if prof_scratch_enabled else prof_promo

    social_active = pricing_config.get('social_discount_active', True)
    default_discount = float(pricing_config.get('social_discount_amount', 200) or 200)
    follow_tiers = [t for t in (pricing_config.get('follow_tiers') or []) if isinstance(t, dict)]

    starter_price = starter_initial
    prof_price = prof_initial
    applied_discount = 0.0
    starter_applied_discount = 0.0
    prof_applied_discount = 0.0

    if social_active and follow_count > 0:
        if follow_tiers:
            sorted_tiers = sorted(follow_tiers, key=_tier_follow_count, reverse=True)
            matched = False
            for tier in sorted_tiers:
                if follow_count >= _tier_follow_count(tier):
                    starter_applied_discount = _tier_plan_discount(tier, 'starter', default_discount)
                    prof_applied_discount = _tier_plan_discount(tier, 'professional', default_discount)
                    starter_price = _tier_plan_charged_price(tier, 'starter', starter_initial, default_discount)
                    prof_price = _tier_plan_charged_price(tier, 'professional', prof_initial, default_discount)
                    applied_discount = starter_applied_discount
                    matched = True
                    break
            if not matched:
                starter_price = max(0.0, starter_initial - default_discount)
                prof_price = max(0.0, prof_initial - default_discount)
                applied_discount = default_discount
                starter_applied_discount = default_discount
                prof_applied_discount = default_discount
        else:
            starter_price = max(0.0, starter_initial - default_discount)
            prof_price = max(0.0, prof_initial - default_discount)
            applied_discount = default_discount
            starter_applied_discount = default_discount
            prof_applied_discount = default_discount

    starter_base = int(round(starter_price))
    starter_gst = round(starter_base * 0.18, 2)
    starter_total = int(round(starter_base + starter_gst))

    prof_base = int(round(prof_price))
    prof_gst = round(prof_base * 0.18, 2)
    prof_total = int(round(prof_base + prof_gst))

    return {
        'starter_full': starter_full,
        'starter_price': starter_price,
        'starter_base': starter_base,
        'starter_gst': starter_gst,
        'starter_total': starter_total,
        'starter_scratch_price': starter_scratch,
        'prof_full': prof_full,
        'prof_price': prof_price,
        'prof_base': prof_base,
        'prof_gst': prof_gst,
        'prof_total': prof_total,
        'prof_scratch_price': prof_scratch,
        'applied_discount': applied_discount,
        'starter_applied_discount': starter_applied_discount,
        'prof_applied_discount': prof_applied_discount,
        'follow_count': follow_count,
    }


from django.core.cache import cache


def _exclusive_base_price(exclusive_config, follow_count=0, discount_unlocked=False):
    """Price shown/charged for the exclusive plan. Matches social-follow + discount-status."""
    config = exclusive_config or {}
    base_price = float(config.get('base_price', 0) or 0)
    follow_tiers = list(config.get('follow_tiers') or [])
    if follow_tiers:
        follow_tiers.sort(key=lambda t: int(t.get('follows', 0) or 0), reverse=True)
        for tier in follow_tiers:
            if follow_count >= int(tier.get('follows', 0) or 0):
                return float(tier.get('price', base_price) or base_price)
        if discount_unlocked:
            easiest = follow_tiers[-1]
            return float(easiest.get('price', config.get('discounted_price', base_price)) or base_price)
        return base_price
    if discount_unlocked:
        return float(config.get('discounted_price', base_price) or base_price)
    return base_price


def _resolve_registration_pincode(pincode):
    """Return a Pincode row from the local table, or fetch/create it from the postal API."""
    pin = str(pincode or '').strip()
    if not re.match(r'^[1-9]\d{5}$', pin):
        return None
    row = Pincode.objects.filter(pincode=pin).first()
    if row:
        return row
    try:
        from apps.home.views.pages import _get_or_create_pincode
        return _get_or_create_pincode(pin)
    except Exception:
        logger.exception('Pincode lookup failed for %s', pin)
        return None


def _to_money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _to_paise(value):
    return int((_to_money(value) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _gst_total_from_inclusive(final_inclusive):
    base = int(round(float(final_inclusive) / 1.18, 0))
    gst = round(base * 0.18, 2)
    total = int(round(base + gst, 0))
    return base, gst, total


def _gst_bundle_from_base(base_amount):
    """GST-exclusive base → (base_rupees, gst, gst_inclusive_total). Matches chooseplan display."""
    base = int(round(float(base_amount or 0)))
    gst = round(base * 0.18, 2)
    total = int(round(base + gst, 0))
    return base, gst, total


def _tier_follow_count(tier):
    try:
        return int((tier or {}).get('follows', 0) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _session_follow_count(request, draft_id):
    followed = request.session.get(f'followed_platforms_{draft_id}') or []
    if isinstance(followed, (list, tuple, set)):
        return len(followed)
    return 0


def _scratch_session_key(plan_type):
    return f'scratch_revealed_{plan_type}'


def _parse_json_flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _parse_displayed_total(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_scratch_enabled(cfg, default=True):
    if not isinstance(cfg, dict) or 'scratch_enabled' not in cfg:
        return default
    return _parse_json_flag(cfg.get('scratch_enabled'))


def _amounts_match(left, right, tolerance=1):
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def _clear_scratch_reveal_session(request):
    """Plans page always starts at full price until the ribbon is scratched again."""
    changed = False
    for plan_type in ('starter', 'professional'):
        key = _scratch_session_key(plan_type)
        if key in request.session:
            request.session.pop(key, None)
            changed = True
    if changed:
        request.session.modified = True


def _scratch_revealed_for_checkout(request, data, plan_type, full_total, discounted_total=None):
    """
    Apply the scratch discount only when this page actually revealed it
    and the order summary is showing that discounted total.
    """
    displayed = _parse_displayed_total((data or {}).get('displayed_total'))
    if displayed is not None and full_total and _amounts_match(displayed, full_total):
        return False
    session_revealed = bool(request.session.get(_scratch_session_key(plan_type)))
    client_revealed = _parse_json_flag((data or {}).get('scratch_revealed'))
    if not (session_revealed and client_revealed):
        return False
    if discounted_total is not None and displayed is not None:
        return _amounts_match(displayed, discounted_total)
    return True


def _plan_payable_total(pricing_config, follow_count, plan_type, scratch_revealed=False, promo_obj=None):
    """
    Charge the amount shown on the card.
    Scratch-enabled plans stay at full_price + GST until the ribbon is revealed.
    """
    if not isinstance(pricing_config, dict):
        pricing_config = dict(_DEFAULT_PRICING)
    starter_cfg = pricing_config.get('starter') or _DEFAULT_PRICING['starter']
    prof_cfg = pricing_config.get('professional') or _DEFAULT_PRICING['professional']
    starter_full = float(starter_cfg.get('full_price', 1999) or 1999)
    prof_full = float(prof_cfg.get('full_price', 9999) or 9999)
    tier_info = _get_tier_prices(pricing_config, follow_count)

    if plan_type == 'starter':
        if promo_obj and not promo_obj.is_free_trial_code() and promo_obj.is_valid('basic'):
            base = max(0.0, starter_full - promo_obj.calculate_discount(starter_full))
            return _gst_bundle_from_base(base)[2]
        if _is_scratch_enabled(starter_cfg) and not scratch_revealed:
            return _gst_bundle_from_base(starter_full)[2]
        return tier_info['starter_total']

    if plan_type == 'professional':
        if promo_obj and not promo_obj.is_free_trial_code() and promo_obj.is_valid('professional'):
            base = max(0.0, prof_full - promo_obj.calculate_discount(prof_full))
            return _gst_bundle_from_base(base)[2]
        if _is_scratch_enabled(prof_cfg) and not scratch_revealed:
            return _gst_bundle_from_base(prof_full)[2]
        return tier_info['prof_total']

    return 0


def _checkout_total_for_plan(pricing_config, follow_count, plan_type, request, data, promo_obj=None):
    """Razorpay amount must match the on-screen order summary."""
    revealed_total = _plan_payable_total(
        pricing_config, follow_count, plan_type, scratch_revealed=True, promo_obj=promo_obj,
    )
    unrevealed_total = _plan_payable_total(
        pricing_config, follow_count, plan_type, scratch_revealed=False, promo_obj=promo_obj,
    )
    cfg_key = 'starter' if plan_type == 'starter' else 'professional'
    default_full = 1999 if plan_type == 'starter' else 9999
    full = float((pricing_config.get(cfg_key) or {}).get('full_price', default_full) or default_full)
    full_total = _gst_bundle_from_base(full)[2]
    if _scratch_revealed_for_checkout(request, data, plan_type, full_total, revealed_total):
        return revealed_total
    return unrevealed_total


def _paise_amounts_match(paid, expected, tolerance=100):
    """Allow ₹1 GST rounding difference between order amount and stored fee."""
    try:
        return abs(int(paid) - int(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def _is_in_progress_razorpay_error(error):
    """Netbanking/UPI redirects fire payment.failed before the bank returns."""
    if not isinstance(error, dict):
        return False
    step = str(error.get('step') or '').strip().lower()
    reason = str(error.get('reason') or '').strip().lower()
    if step in ('payment_authentication', 'payment_capture', 'payment_redirect', 'redirect'):
        return True
    if reason in ('payment_pending', 'payment_redirect'):
        return True
    return False


def _session_owns_agent(request, agent):
    """True when this browser session legitimately belongs to ``agent``.

    Payment endpoints must never log a session into an agent chosen by the
    request payload — only the agent this session started checkout for (or is
    already signed in as) may be logged in after payment verification.
    """
    if not agent or not getattr(agent, 'pk', None):
        return False
    pending = request.session.get('pending_checkout') or {}
    candidates = (pending.get('agent_id'), request.session.get('agent_id'))
    if any(str(c) == str(agent.pk) for c in candidates if c):
        return True
    user = getattr(request, 'user', None)
    return bool(
        user is not None
        and user.is_authenticated
        and agent.user_id
        and agent.user_id == user.pk
    )


def _recover_pending_razorpay_checkout(request, payload=None, retry=False):
    """
    After netbanking the browser often reloads /chooseplan/ instead of
    calling verify-payment. If Razorpay already captured the payment, finish it.
    """
    pending = request.session.get('pending_checkout') or {}
    payload = payload or {}
    # Only the server-side checkout session may choose the agent. A client
    # supplied agent_id/order_id previously let anyone log in as any paid agent.
    agent_id = pending.get('agent_id')
    order_id = pending.get('order_id') or payload.get('razorpay_order_id')
    from apps.agents.models import Agent, AgentSubscription

    agent = Agent.objects.filter(pk=agent_id).first() if agent_id else None
    if not agent and order_id:
        sub = AgentSubscription.objects.filter(razorpay_order_id=order_id).first()
        if sub:
            agent = sub.agent
    if not agent:
        return None
    if not verify_and_activate_pending_payment(agent):
        if not retry:
            return None
        for _attempt in range(3):
            time.sleep(1)
            if verify_and_activate_pending_payment(agent):
                break
        else:
            return None

    from apps.agents.services.account_auth import agent_can_access_dashboard
    agent.refresh_from_db()
    if not agent_can_access_dashboard(agent):
        logger.warning(
            'Pending checkout recovery aborted for agent #%s: payment not captured.',
            getattr(agent, 'id', None),
        )
        return None

    if not _session_owns_agent(request, agent):
        # Payment is verified and activated, but this browser did not start the
        # checkout — send it to the normal login page instead of signing it in.
        logger.warning(
            'Pending checkout recovery for agent #%s from a session that does not own it; login skipped.',
            getattr(agent, 'id', None),
        )
        return reverse('agents:agent_login')

    try:
        user = create_or_link_django_user(agent)
        login_agent_user(request, user)
    except Exception as login_err:
        logger.error('Pending checkout login failed for agent %s: %s', getattr(agent, 'id', None), login_err)

    request.session.pop('current_draft_id', None)
    request.session.pop('reg_step', None)
    request.session.pop('ref_code', None)
    request.session.pop('pending_checkout', None)

    from apps.distributors.views.dashboard import is_distributor
    if request.user.is_authenticated and is_distributor(request.user):
        return reverse('distributors:agents_index')
    return reverse('agents:payment_complete')


def _is_plan_upgrade_payment(agent, order_id=None):
    """True when the agent already had a completed subscription before this order."""
    if not agent:
        return False
    from apps.agents.models import AgentSubscription
    qs = AgentSubscription.objects.filter(agent=agent, payment_status='completed')
    if order_id:
        qs = qs.exclude(razorpay_order_id=order_id)
    return qs.exists()


def _deactivate_superseded_subscriptions(agent, keep_subscription_id):
    """Keep only the latest paid subscription active after an upgrade."""
    if not agent or not keep_subscription_id:
        return
    from apps.agents.models import AgentSubscription
    AgentSubscription.objects.filter(
        agent=agent,
        status='active',
    ).exclude(pk=keep_subscription_id).update(status='inactive')


def _display_plan_name(agent, pricing_config):
    """Dashboard header plan label — checks active subscription selected_plan first to match admin listing, falling back to agent.plan_type slug."""
    from apps.agents.services.feature_unlock import normalize_plan_slug, plan_slug_from_name

    active_sub = getattr(agent, 'activeSubscription', None)
    if not active_sub and hasattr(agent, 'subscriptions'):
        try:
            active_sub = (
                agent.subscriptions.filter(status='active')
                .order_by('-starts_at', '-created_at', '-id')
                .first()
            ) or agent.subscriptions.order_by('-id').first()
        except Exception:
            active_sub = None

    if active_sub and active_sub.selected_plan:
        raw_plan = str(active_sub.selected_plan).strip()
        try:
            decoded = json.loads(raw_plan)
            if isinstance(decoded, dict) and decoded.get('name'):
                raw_plan = str(decoded['name']).strip()
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        if raw_plan:
            slug_from_sub = plan_slug_from_name(raw_plan)
            label = paid_plan_label(raw_plan)
            if label in (PLAN_LABELS['starter'], PLAN_LABELS['professional']):
                return label
            return raw_plan

    slug = normalize_plan_slug(getattr(agent, 'plan_type', '') or '')
    if slug == 'free_trial':
        return 'Free Trial'
    if slug == 'exclusive':
        from apps.home.models import SiteSetting
        ex_cfg = SiteSetting.get_value('exclusive_plan_config') or {}
        return ex_cfg.get('name') or 'Exclusive Plan'

    return paid_plan_label(slug or 'starter')


def _razorpay_callback_payload(request):
    data = {}
    if request.method == 'POST':
        content_type = (request.content_type or '').lower()
        if 'json' in content_type:
            try:
                data = json.loads(request.body or '{}')
            except json.JSONDecodeError:
                data = request.POST.dict()
        else:
            data = request.POST.dict()
    else:
        data = request.GET.dict()
    pending = request.session.get('pending_checkout') or {}
    return {
        'razorpay_payment_id': data.get('razorpay_payment_id'),
        'razorpay_order_id': data.get('razorpay_order_id') or pending.get('order_id'),
        'razorpay_signature': data.get('razorpay_signature'),
        # Never trust a client-supplied agent_id: it selects whose session gets
        # logged in. Only the server-side checkout session may name the agent.
        'agent_id': pending.get('agent_id'),
        'plan_type': data.get('plan_type') or pending.get('plan_type'),
        'plan_name': data.get('plan_name') or pending.get('plan_name'),
        'error': data.get('error') or {
            'code': data.get('error[code]') or data.get('error_code'),
            'description': data.get('error[description]') or data.get('error_description'),
            'step': data.get('error[step]'),
            'reason': data.get('error[reason]'),
        },
    }


def _expected_amount_paise(registration_amount):
    return _to_paise(registration_amount)


def _get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')

# ─── Helper ─────────────────────────────────────────────────────────────────────


def _get_registration_context(request):
    """Build the template context based on current session state."""
    session = request.session
    reg_step = session.get('reg_step', 0)
    email_verified = session.get('email_verified', False)
    verified_email = session.get('verified_email', '')

    # Load draft if exists
    draft = None
    draft_id = session.get('current_draft_id')
    if draft_id:
        try:
            draft = AgentDraft.objects.get(pk=draft_id)
        except AgentDraft.DoesNotExist:
            pass

    layout_template = 'base.html'
    try:
        from apps.distributors.views.dashboard import is_distributor
        if request.user.is_authenticated and is_distributor(request.user):
            layout_template = 'distributors/layout.html'
    except Exception:
        pass

    active_investment_types = []
    try:
        from apps.agents.models import InvestmentType
        active_investment_types = list(InvestmentType.objects.filter(is_active=True))
    except Exception as e:
        logger.warning(f"Error fetching active_investment_types: {e}")

    prefilled_promo = ''
    try:
        from apps.agents.models import PromoCode
        promo_param = (request.GET.get('promo') or '').strip().upper()
        if promo_param:
            p_obj = PromoCode.objects.filter(code__iexact=promo_param).first()
            if p_obj and p_obj.is_valid():
                prefilled_promo = p_obj.code
                request.session['applied_promo_code'] = p_obj.code
        elif request.session.get('applied_promo_code'):
            p_obj = PromoCode.objects.filter(code__iexact=request.session.get('applied_promo_code')).first()
            if p_obj and p_obj.is_valid():
                prefilled_promo = p_obj.code
            else:
                request.session.pop('applied_promo_code', None)
    except Exception as e:
        logger.warning(f"Error resolving promo code in registration context: {e}")

    swipe = {}
    try:
        from apps.admin_panel.views.content import get_registration_swipe_config
        swipe = get_registration_swipe_config(visible_only=True)
    except Exception as e:
        logger.warning(f"Error resolving registration swipe config: {e}")
        swipe = {'enabled': False, 'slides': []}

    default_states = ALL_INDIAN_STATES
    try:
        fetched_states = list(Pincode.objects.values_list('state', flat=True).distinct().order_by('state'))
        if fetched_states:
            default_states = fetched_states
    except Exception as e:
        logger.warning(f"Error fetching pincodes table/states: {e}")

    return {
        'layout_template': layout_template,
        'reg_step': reg_step,
        'email_verified': email_verified,
        'verified_email': verified_email,
        'draft': draft,
        'default_states': default_states,
        'segments': INSURANCE_SEGMENTS,
        'language_options': LANGUAGE_OPTIONS,
        'agent_segments': getattr(draft, 'segments', []) if draft else [],
        'agent_languages': getattr(draft, 'languages', []) if draft else [],
        'active_investment_types': active_investment_types,
        'prefilledPromo': prefilled_promo,
        'registration_swipe_enabled': bool(swipe.get('enabled')) and bool(swipe.get('slides')),
        'registration_swipe_slides': swipe.get('slides') or [],
        'preview_auto_advance_ms': int(swipe.get('preview_auto_advance_seconds') or 2) * 1000,
        'hide_site_nav': True,
        'hide_footer': True,
        'hide_chatbot': True,
    }


# ─── Views ──────────────────────────────────────────────────────────────────────

def _build_referring_agent_data(referring_agent, is_championship=False):
    """Build standardized dictionary for referring agent card and OG preview."""
    if not referring_agent:
        return None

    photo_url = '/static/img/avatar-icon.jpg'
    try:
        profile = getattr(referring_agent, 'profile', None)
        if profile and hasattr(profile, 'profile_photo_url'):
            photo_url = profile.profile_photo_url or photo_url
        elif referring_agent.photo:
            photo_url = referring_agent.photo.url
    except Exception:
        pass

    avg_rating = 0.0
    review_count = 0
    try:
        avg_rating = round(float(referring_agent.average_rating), 1)
        review_count = referring_agent.review_count
    except Exception:
        pass

    profile_slug = referring_agent.agent_slug
    profile_url = f'/profile/{referring_agent.state_code}/{profile_slug}/' if profile_slug else ''

    name = referring_agent.fullname or ''
    initials = ''.join(word[0].upper() for word in name.split()[:2] if word) or 'A'

    segments = []
    try:
        raw_segs = referring_agent.ordered_insurance_segments
        for seg_item in raw_segs:
            s_lower = str(seg_item).strip().lower()
            if s_lower == 'sme':
                name_seg = 'SME'
                badge_cls = 'bg-purple-50 text-purple-700 border-purple-200/80'
            elif 'health' in s_lower:
                name_seg = 'Health'
                badge_cls = 'bg-emerald-50 text-emerald-700 border-emerald-200/80'
            elif 'life' in s_lower:
                name_seg = 'Life'
                badge_cls = 'bg-blue-50 text-blue-700 border-blue-200/80'
            elif 'motor' in s_lower:
                name_seg = 'Motor'
                badge_cls = 'bg-amber-50 text-amber-700 border-amber-200/80'
            else:
                name_seg = s_lower.replace('_', ' ').title()
                badge_cls = 'bg-slate-100 text-slate-700 border-slate-200'
            segments.append({'id': s_lower, 'name': name_seg, 'badge_cls': badge_cls})
    except Exception:
        pass

    return {
        'id': referring_agent.id,
        'name': name,
        'fullname': referring_agent.fullname or name,
        'initials': initials,
        'photo_url': photo_url,
        'avg_rating': avg_rating if avg_rating > 0 else 5.0,
        'review_count': review_count,
        'profile_url': profile_url,
        'segments': segments,
        'slug': profile_slug,
        'is_championship': bool(is_championship),
        'og_image_url': '/static/img/championship_og.jpg' if is_championship else reverse('agents:agent_og_image', kwargs={'agent_id': referring_agent.id}),
    }


@require_http_methods(["GET"])
def agent_registration(request):
    """Render the registration page. Shows OTP, Step 1, or Step 2 based on session."""
    try:
        if request.user.is_authenticated:
            from apps.agents.services.account_auth import resolve_agent_for_user, agent_can_access_dashboard
            if request.user.is_staff or request.user.is_superuser:
                return redirect('agents:agent_dashboard')
            agent = resolve_agent_for_user(request.user)
            if agent:
                if agent_can_access_dashboard(agent):
                    return redirect('agents:agent_dashboard')
                return redirect('agents:chooseplan')

        # Capture referral parameter if provided in GET query params (?ref= or ?refCode=)
        ref_param = request.GET.get('ref') or request.GET.get('refCode')
        referring_agent_data = None
        if ref_param:
            ref_val = str(ref_param).strip().upper()
            request.session['ref_code'] = ref_val
            referring_agent = None
            is_champ = False

            if ref_val.startswith('PA-'):
                try:
                    from apps.referral_championship.services.attribution_service import bind_referral_session
                    bind_referral_session(request, ref_val)
                    from apps.referral_championship.models import ChampionshipParticipant
                    participant = ChampionshipParticipant.objects.filter(referral_id=ref_val).select_related('agent').first()
                    if participant and participant.agent:
                        referring_agent = participant.agent
                        is_champ = True
                except Exception:
                    pass

            if not referring_agent:
                try:
                    from apps.distributors.models import SubDistributor
                    sub_dist = SubDistributor.objects.filter(code=ref_val, status='active').first()
                    if sub_dist:
                        request.session['sub_distributor_id'] = sub_dist.id
                        request.session['distributor_id'] = sub_dist.distributor_id
                        request.session['distributor_led_registration'] = True
                        request.session['ref_code'] = sub_dist.code
                except Exception:
                    pass

            if not referring_agent and not request.session.get('sub_distributor_id'):
                try:
                    from apps.admin_panel.models.referral_code import ReferralCode
                    ref_obj = ReferralCode.objects.filter(code=ref_val, is_active=True).select_related('agent').first()
                    if ref_obj:
                        if ref_obj.distributor_id:
                            request.session['distributor_id'] = ref_obj.distributor_id
                            request.session['distributor_led_registration'] = True
                        if ref_obj.agent:
                            referring_agent = ref_obj.agent
                except Exception:
                    pass

            if referring_agent:
                referring_agent_data = _build_referring_agent_data(referring_agent, is_championship=is_champ)

        context = _get_registration_context(request)
        if referring_agent_data:
            context['referring_agent'] = referring_agent_data
        return render(request, 'agents/registration.html', context)
    except Exception as e:
        logger.exception(f"Error in agent_registration view: {e}")
        context = _get_registration_context(request)
        return render(request, 'agents/registration.html', context)


@require_http_methods(["GET"])
def agent_registration_referral(request, ref_code):
    """
    Referral registration landing — /agent-registration/join/{ref_code}/
    Stores the referral code in session, looks up the referring agent,
    and renders the same registration page with the referring agent's card.
    The actual registration flow remains completely unchanged.
    """
    try:
        # If already logged in, redirect same as normal registration
        if request.user.is_authenticated:
            from apps.agents.services.account_auth import resolve_agent_for_user, agent_can_access_dashboard
            if request.user.is_staff or request.user.is_superuser:
                return redirect('agents:agent_dashboard')
            agent = resolve_agent_for_user(request.user)
            if agent:
                if agent_can_access_dashboard(agent):
                    return redirect('agents:agent_dashboard')
                return redirect('agents:chooseplan')

        code_val = str(ref_code).strip().upper()

        # ── Store ref code in session for the existing flow to pick up ──
        request.session['ref_code'] = code_val

        # ── Look up the referring agent ──
        referring_agent = None
        is_champ = False

        # 1. Try Championship participant code (PA-XXXXXX)
        if code_val.startswith('PA-'):
            try:
                from apps.referral_championship.services.attribution_service import bind_referral_session
                bind_referral_session(request, code_val)
                from apps.referral_championship.models import ChampionshipParticipant
                participant = ChampionshipParticipant.objects.filter(referral_id=code_val).select_related('agent').first()
                if participant and participant.agent:
                    referring_agent = participant.agent
                    is_champ = True
            except Exception:
                pass

        # 2. Try SubDistributor code
        if not referring_agent:
            try:
                from apps.distributors.models import SubDistributor
                sub_dist = SubDistributor.objects.filter(code=code_val, status='active').first()
                if sub_dist:
                    sub_dist.clicks = (sub_dist.clicks or 0) + 1
                    sub_dist.save(update_fields=['clicks'])
                    request.session['sub_distributor_id'] = sub_dist.id
                    request.session['distributor_id'] = sub_dist.distributor_id
                    request.session['distributor_led_registration'] = True
                    request.session['ref_code'] = sub_dist.code
            except Exception:
                pass

        # 3. Try legacy ReferralCode
        if not referring_agent and not request.session.get('sub_distributor_id'):
            try:
                from apps.admin_panel.models.referral_code import ReferralCode
                ref_obj = ReferralCode.objects.filter(code=code_val, is_active=True).select_related('agent').first()
                if ref_obj:
                    # Increment clicks for tracking
                    ref_obj.clicks = (ref_obj.clicks or 0) + 1
                    ref_obj.save(update_fields=['clicks'])
                    if ref_obj.distributor_id:
                        request.session['distributor_id'] = ref_obj.distributor_id
                        request.session['distributor_led_registration'] = True
                    if ref_obj.agent:
                        referring_agent = ref_obj.agent
            except Exception:
                pass

        # ── Build referring agent context for the card ──
        referring_agent_data = _build_referring_agent_data(referring_agent, is_championship=is_champ) if referring_agent else None

        # ── Build normal registration context + referring agent ──
        context = _get_registration_context(request)
        context['referring_agent'] = referring_agent_data
        return render(request, 'agents/registration.html', context)
    except Exception as e:
        logger.exception(f"Error in agent_registration_referral view for ref_code {ref_code}: {e}")
        context = _get_registration_context(request)
        return render(request, 'agents/registration.html', context)


def _int_or_zero(value):
    try:
        digits = re.sub(r'\D', '', str(value or ''))
        return int(digits) if digits else 0
    except (TypeError, ValueError):
        return 0


def _unique_profile_slug(desired, exclude_pk=None):
    from django.utils.text import slugify
    from apps.agents.models import AgentProfile

    base = slugify(desired or '') or 'agent'
    slug = base
    n = 1
    while True:
        qs = AgentProfile.objects.filter(slug=slug)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return slug
        slug = f'{base}-{n}'
        n += 1


def _public_profile_path(agent):
    slug = ''
    try:
        profile = getattr(agent, 'profile', None)
        slug = (profile.slug or '') if profile else ''
    except Exception:
        slug = ''
    if not slug:
        slug = getattr(agent, 'agent_slug', '') or ''
    if not slug:
        return reverse('agents:agent_dashboard')
    
    return f"/{slug}/"


def _activation_success_payload(request, agent, message='Payment successful and account activated.'):
    from apps.distributors.views.dashboard import is_distributor

    redirect_url = reverse('agents:agent_dashboard')
    try:
        if request.user.is_authenticated and is_distributor(request.user):
            redirect_url = reverse('distributors:agents_index')
    except Exception:
        pass
    profile_path = _public_profile_path(agent)
    return {
        'success': True,
        'message': message,
        'redirect_url': redirect_url,
        'agent_name': (getattr(agent, 'fullname', '') or '').strip(),
        'profile_url': request.build_absolute_uri(profile_path),
    }


# Real image format (detected from the file bytes) -> extension it is saved with.
_PHOTO_FORMAT_EXTENSIONS = {
    'JPEG': '.jpg', 'MPO': '.jpg', 'PNG': '.png', 'GIF': '.gif',
    'WEBP': '.webp', 'BMP': '.bmp',
}


def _validated_photo_upload(upload):
    """Return the upload only if it is a real raster image (<=5MB), else None.

    Model ImageFields do not validate on assignment, so an anonymous visitor
    could store e.g. evil.html / script-laden SVG under /media/agent_photos/,
    which is then served same-origin.

    The check uses the file content, not its name, so real photos named
    .jfif / .JPG / without extension (Android pickers) keep working; the
    stored name gets the extension of the detected format.
    """
    if not upload:
        return None
    if upload.size > 5 * 1024 * 1024:
        return None
    try:
        from PIL import Image
        upload.seek(0)
        img = Image.open(upload)
        fmt = (img.format or '').upper()
        img.verify()
        upload.seek(0)
    except Exception:
        return None
    ext = _PHOTO_FORMAT_EXTENSIONS.get(fmt)
    if not ext:
        return None
    base = os.path.splitext(os.path.basename(upload.name or ''))[0]
    base = re.sub(r'[^A-Za-z0-9_-]+', '_', base).strip('_')[:80] or 'photo'
    upload.name = f'{base}{ext}'
    return upload


def _assign_step1_draft_fields(draft, request, extra=None):
    extra = extra or {}
    draft.fullname = extra.get('fullname', request.POST.get('fullname', '').strip())
    draft.mobile = extra.get('mobile', request.POST.get('mobile', '').strip())
    draft.agent_pincode = extra.get('agent_pincode', request.POST.get('agent_pincode', '').strip())
    draft.state = extra.get('state', request.POST.get('state', '').strip())
    exp_raw = extra.get('experience', request.POST.get('experience_range', ''))
    if exp_raw:
        try:
            exp_digits = re.sub(r'\D', '', str(exp_raw))
            if exp_digits and int(exp_digits) > 60:
                exp_raw = '60'
        except (TypeError, ValueError):
            pass
    draft.experience_range = exp_raw
    draft.segments = extra.get('segments', request.POST.getlist('segments[]') or request.POST.getlist('segments'))
    draft.investment_types = extra.get(
        'investment_types',
        request.POST.getlist('investment_types[]') or request.POST.getlist('investment_types'),
    )
    draft.promo_code = extra.get('promo_code', request.POST.get('promo_code', '').strip())
    draft.address = extra.get('address', request.POST.get('address', '').strip())
    draft.client_base = extra.get('client_base', request.POST.get('client_base', '').strip())
    draft.slug = extra.get('slug', request.POST.get('slug', '').strip())
    draft.whatsapp = extra.get('whatsapp', request.POST.get('whatsapp', '').strip())
    draft.pan_number = extra.get('pan_number', request.POST.get('pan_number', '').strip().upper())
    draft.claims_settled = extra.get('claims_settled', _int_or_zero(request.POST.get('claims_settled')))
    draft.claim_amount = extra.get('claim_amount', request.POST.get('claim_amount', '').strip())
    photo = _validated_photo_upload(request.FILES.get('photo'))
    if photo:
        draft.photo = photo

    # Capture sub-distributor / distributor binding from session
    sub_dist_id_from_session = request.session.get('sub_distributor_id')
    if sub_dist_id_from_session:
        draft.sub_distributor_id = sub_dist_id_from_session

    dist_id_from_session = request.session.get('distributor_id')
    if dist_id_from_session:
        draft.distributor_id = dist_id_from_session
        from apps.admin_panel.models.referral_code import ReferralCode
        ref_obj = ReferralCode.objects.filter(distributor_id=dist_id_from_session, is_active=True).first()
        if ref_obj:
            draft.referred_by_code = ref_obj.code
    else:
        ref_code = request.session.get('ref_code') or request.session.get('championship_ref_id')
        if ref_code:
            from apps.distributors.models import SubDistributor
            sub_dist = SubDistributor.objects.filter(code=ref_code, status='active').first()
            if sub_dist:
                draft.sub_distributor_id = sub_dist.id
                draft.distributor_id = sub_dist.distributor_id
                draft.referred_by_code = sub_dist.code
            elif str(ref_code).startswith('PA-'):
                draft.referred_by_code = ref_code
            else:
                from apps.admin_panel.models.referral_code import ReferralCode
                ref_obj = ReferralCode.objects.filter(code=ref_code, is_active=True).first()
                if ref_obj:
                    draft.referred_by_code = ref_code
                    if ref_obj.distributor_id:
                        draft.distributor_id = ref_obj.distributor_id

    return draft


@require_http_methods(["GET"])
def check_slug_availability(request):
    """Check if a custom slug is available for an agent profile."""
    from django.utils.text import slugify
    from apps.agents.models import AgentProfile
    from apps.home.models.page import Page

    raw_slug = request.GET.get('slug', '').strip()
    if not raw_slug:
        return JsonResponse({'success': False, 'available': False, 'message': 'Slug is required.'})

    slug = slugify(raw_slug)

    RESERVED_SLUGS = {
        'admin', 'django-admin', 'about', 'contact', 'terms', 'privacy', 'faq',
        'find-agents', 'calculators', 'calculator', 'coming-soon', 'lic-agent',
        'cancellation-refund-policy', 'blacklisted-agents', 'marketing', 'media',
        'static', 'agent-registration', 'agent-register-step1', 'agent-register-step2',
        'agent-login', 'forgot-password', 'reset-password', 'agent-logout', 'logout',
        'profile', 'card', 'review', 'review-card', 'join', 'auth', 'events',
        'chatbot-api', 'championship', 'insurance', 'insurance-login', 'api',
        'manifest.webmanifest', 'sw.js', 'offline.html', 'sitemap.xml', 'robots.txt'
    }

    if slug.lower() in RESERVED_SLUGS or Page.objects.filter(slug=slug).exists() or AgentProfile.objects.filter(slug=slug).exists():
        return JsonResponse({
            'success': True,
            'available': False,
            'slug': slug,
            'message': 'This URL is already taken. Please choose another.',
        })
    return JsonResponse({
        'success': True,
        'available': True,
        'slug': slug,
        'message': 'URL is available!',
    })


@require_http_methods(["GET"])
def check_email_availability(request):
    """Tell the registration form if this email already belongs to an active/paid agent."""
    from apps.agents.models import Agent, Invoice

    email = (request.GET.get('email') or '').strip().lower()
    if not email or '@' not in email:
        return JsonResponse({
            'success': False,
            'registered': False,
            'valid': False,
            'message': 'Please enter a valid email address.',
        })

    registered = (
        Invoice.objects.filter(agent_email__iexact=email, payment_status='paid').exists()
        or Agent.objects.filter(email__iexact=email, status__in=['active', 'pending_approval']).exists()
    )
    if registered:
        return JsonResponse({
            'success': True,
            'registered': True,
            'valid': True,
            'message': f'You are already registered with {email}. Please login to access your dashboard.',
            'login_url': reverse('agents:agent_login'),
        })
    return JsonResponse({
        'success': True,
        'registered': False,
        'valid': True,
        'message': '',
    })


@require_POST
@csrf_protect
def register_step1(request):
    """Save Step 1 (basic info) → create/update AgentDraft."""
    # Extract form data
    fullname = request.POST.get('fullname', '').strip()
    email = request.POST.get('email', '').strip().lower()
    mobile = request.POST.get('mobile', '').strip()
    agent_pincode = request.POST.get('agent_pincode', '').strip()
    state = request.POST.get('state', '').strip()
    experience = request.POST.get('experience_range', '')
    if experience:
        try:
            exp_digits = re.sub(r'\D', '', str(experience))
            if exp_digits and int(exp_digits) > 60:
                experience = '60'
        except (TypeError, ValueError):
            pass
    segments = request.POST.getlist('segments[]') or request.POST.getlist('segments')
    investment_types = request.POST.getlist('investment_types[]') or request.POST.getlist('investment_types')
    promo_code = request.POST.get('promo_code', '').strip()
    address = request.POST.get('address', '').strip()
    client_base = request.POST.get('client_base', '').strip()
    slug = request.POST.get('slug', '').strip()

    distributor_id = None
    from apps.distributors.views.dashboard import is_distributor
    if request.user.is_authenticated and is_distributor(request.user):
        from apps.admin_panel.models import User as LaravelUser
        l_user = LaravelUser.objects.filter(email=request.user.email).first()
        distributor_id = l_user.id if l_user else request.user.id
        request.session['distributor_id'] = distributor_id

    # Validation
    errors = []
    field_errors = {}
    if not fullname:
        errors.append('Full name is required.')
    elif re.search(r'[<>]', fullname) or len(fullname) > 255:
        # Names are rendered on public pages and in JS-built HTML.
        errors.append('Full name contains invalid characters.')
    if not email or '@' not in email:
        errors.append('Please enter a valid email address.')
    if not mobile or not re.match(r'^[6-9]\d{9}$', mobile):
        errors.append('Please enter a valid 10-digit mobile number starting with 6-9.')
    whatsapp = request.POST.get('whatsapp', '').strip()
    if whatsapp and not re.match(r'^[6-9]\d{9}$', whatsapp):
        errors.append('Please enter a valid 10-digit WhatsApp number starting with 6-9.')
    if not agent_pincode or not re.match(r'^[1-9]\d{5}$', agent_pincode):
        msg = 'Please enter a valid 6-digit pincode.'
        errors.append(msg)
        field_errors['agent_pincode'] = [msg]
    else:
        pin_row = _resolve_registration_pincode(agent_pincode)
        if not pin_row:
            msg = 'This pincode was not found. Please enter a valid pincode.'
            errors.append(msg)
            field_errors['agent_pincode'] = [msg]
        elif not state:
            state = (pin_row.state or '').strip()
    if not state:
        errors.append('Please select a state.')
    if not segments and not investment_types:
        errors.append('Please select at least one insurance segment or investment type.')
    pan_number = request.POST.get('pan_number', '').strip().upper()
    if pan_number and not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]$', pan_number):
        errors.append('PAN must be 5 letters, 4 digits, then 1 letter (e.g. ABCDE1234F).')

    if errors:
        payload = {'success': False, 'message': ' '.join(errors)}
        if field_errors:
            payload['errors'] = field_errors
        return JsonResponse(payload, status=400)

    from django.contrib.auth.models import User
    from apps.agents.models import Agent, Invoice, AgentDraft

    # Check if a paid invoice or active agent exists matching this email
    paid_agent_exists = (
        Invoice.objects.filter(agent_email__iexact=email, payment_status='paid').exists()
        or Agent.objects.filter(email__iexact=email, status__in=['active', 'pending_approval']).exists()
    )
    if paid_agent_exists:
        return JsonResponse({
            'success': False,
            'message': f'You are already registered with {email}. Please login to access your dashboard.',
            'redirect': '/agent-login/'
        }, status=422)

    # Check if an Agent record already exists for the email but has NO paid invoice
    existing_agent = Agent.objects.filter(email=email).first()
    if existing_agent:
        # Case 4 (network lost): try to verify Razorpay payment directly first!
        if verify_and_activate_pending_payment(existing_agent):
            return JsonResponse({
                'success': True,
                'message': 'Payment verified successfully! Redirecting to dashboard...',
                'redirect': reverse('agents:agent_dashboard'),
            })

        # Reuse existing registration (Agent and AgentDraft)
        draft = AgentDraft.objects.filter(email=email).first()
        if not draft:
            session_key = request.session.session_key
            if not session_key:
                request.session.create()
                session_key = request.session.session_key
            draft = AgentDraft(session_key=session_key, email=email)

        _assign_step1_draft_fields(draft, request)
        draft.email = email
        draft.email_verified = True
        draft.registration_step = 1
        if draft.promo_code:
            request.session['applied_promo_code'] = draft.promo_code
        elif not request.session.get('distributor_led_registration') and not request.session.get('distributor_id'):
            request.session.pop('applied_promo_code', None)
        draft.save()

        request.session['current_draft_id'] = draft.pk
        request.session['reg_step'] = 2

        # Update the existing Agent record to prevent stale data
        existing_agent.fullname = draft.fullname
        existing_agent.mobile = draft.mobile
        existing_agent.agent_pincode = draft.agent_pincode
        existing_agent.experience_range = draft.experience_range
        existing_agent.client_base = draft.client_base
        existing_agent.save()

        logger.info(f'Agent Step 1 reused & updated — draft #{draft.pk}, email={email}')

        # ── Event: FORM_SUBMIT (existing agent reuse) ───────────────────────
        RegistrationActivityLog.log(
            RegistrationActivityLog.EVENT_FORM_SUBMIT,
            request=request,
            agent=existing_agent,
            draft_id=draft.pk,
            extra_details={
                'email': email,
                'fullname': draft.fullname,
                'agent_pincode': draft.agent_pincode,
                'state': draft.state,
                'promo_code': draft.promo_code or '',
                'reuse': True,
            },
        )

        if getattr(draft, 'distributor_id', None) or getattr(draft, 'referred_by_code', None):
            RegistrationActivityLog.log(
                RegistrationActivityLog.EVENT_DISTRIBUTION,
                request=request,
                agent=existing_agent,
                draft_id=draft.pk,
                extra_details={
                    'distributor_id': draft.distributor_id,
                    'referred_by_code': draft.referred_by_code,
                    'via_ref_code': True if getattr(draft, 'referred_by_code', None) and not getattr(draft, 'distributor_id', None) else False,
                    'reuse': True,
                },
            )


        return JsonResponse({
            'success': True,
            'message': 'Basic information updated!',
            'redirect': '/chooseplan/',
        })

    # Create new draft
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    draft_id = request.session.get('current_draft_id')
    if draft_id:
        try:
            draft = AgentDraft.objects.get(pk=draft_id)
        except AgentDraft.DoesNotExist:
            draft = AgentDraft(session_key=session_key)
    else:
        draft = AgentDraft(session_key=session_key)

    draft.email = email
    _assign_step1_draft_fields(draft, request)
    draft.email_verified = True
    draft.registration_step = 1
    if draft.promo_code:
        request.session['applied_promo_code'] = draft.promo_code
    elif not request.session.get('distributor_led_registration') and not request.session.get('distributor_id'):
        request.session.pop('applied_promo_code', None)
    draft.save()

    request.session['current_draft_id'] = draft.pk
    request.session['reg_step'] = 2

    logger.info(f'Agent Step 1 saved — draft #{draft.pk}, email={email}')

    # ── Event: FORM_SUBMIT ──────────────────────────────────────────────────
    RegistrationActivityLog.log(
        RegistrationActivityLog.EVENT_FORM_SUBMIT,
        request=request,
        draft_id=draft.pk,
        extra_details={
            'email': email,
            'fullname': draft.fullname,
            'agent_pincode': draft.agent_pincode,
            'state': draft.state,
            'plan_type': '',
            'promo_code': draft.promo_code or '',
        },
    )

    if getattr(draft, 'distributor_id', None) or getattr(draft, 'referred_by_code', None):
        RegistrationActivityLog.log(
            RegistrationActivityLog.EVENT_DISTRIBUTION,
            request=request,
            draft_id=draft.pk,
            extra_details={
                'distributor_id': draft.distributor_id,
                'referred_by_code': draft.referred_by_code,
                'via_ref_code': True if getattr(draft, 'referred_by_code', None) and not getattr(draft, 'distributor_id', None) else False,
            },
        )

    return JsonResponse({
        'success': True,
        'message': 'Basic information saved!',
        'redirect': '/chooseplan/',
    })


@require_POST
@csrf_protect
def register_step2(request):
    """Save Step 2 (profile details) → advance to plan selection."""
    draft_id = request.session.get('current_draft_id')
    if not draft_id:
        return JsonResponse({'success': False, 'message': 'Registration session not found. Please start over.'}, status=400)

    try:
        draft = AgentDraft.objects.get(pk=draft_id)
    except AgentDraft.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Registration data not found.'}, status=400)

    # Extract form data
    about = request.POST.get('about', '').strip()
    languages = request.POST.getlist('languages[]') or request.POST.getlist('languages')
    certifications = request.POST.get('certifications', '').strip()

    # Handle photo upload
    raw_photo = request.FILES.get('photo')
    photo = _validated_photo_upload(raw_photo)
    if raw_photo and not photo:
        return JsonResponse({
            'success': False,
            'message': 'Profile photo must be a JPG, PNG, GIF or WEBP image under 5MB.',
        }, status=422)
    if photo:
        draft.photo = photo

    draft.about = about
    draft.languages = languages
    draft.certifications = certifications
    draft.registration_step = 2
    draft.save()

    request.session['reg_step'] = 3  # Ready for payment/plans

    logger.info(f'Agent Step 2 saved — draft #{draft.pk}')

    return JsonResponse({
        'success': True,
        'message': 'Profile saved! Redirecting to plans...',
        'redirect': '/chooseplan/',
    })


_SOCIAL_FOLLOW_PLATFORMS = frozenset({
    'instagram', 'facebook', 'x', 'twitter', 'linkedin', 'youtube',
    'whatsapp', 'telegram', 'threads', 'pinterest',
})


@require_POST
def record_social_follow(request):
    """Record that the user successfully followed social accounts and compute plan discounts."""
    import json
    try:
        data = json.loads(request.body)
        platform = str(data.get('platform') or '').strip().lower()[:50]
        agent_id = data.get('agent_id')  # draft_id
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON.'}, status=400)

    if not agent_id or not platform:
        return JsonResponse({'success': False, 'message': 'Missing data.'}, status=400)
    from apps.home.models import SiteSetting
    pricing_config = SiteSetting.get_value('pricing_config', _DEFAULT_PRICING)

    # Each distinct platform raises the discount tier, so only real/configured
    # networks count — arbitrary strings ("a","b","c",...) unlocked the top tier.
    allowed_platforms = set(_SOCIAL_FOLLOW_PLATFORMS)
    exclusive_cfg = SiteSetting.get_value('exclusive_plan_config') or {}
    for cfg in (pricing_config, exclusive_cfg):
        links = cfg.get('social_links') if isinstance(cfg, dict) else None
        for link in links or []:
            if isinstance(link, dict) and link.get('platform'):
                allowed_platforms.add(str(link['platform']).strip().lower())
    if platform not in allowed_platforms:
        return JsonResponse({'success': False, 'message': 'Unknown platform.'}, status=400)

    session_key = f'followed_platforms_{agent_id}'
    followed = request.session.get(session_key, [])
    if platform not in followed:
        followed.append(platform)
        request.session[session_key] = followed
        if hasattr(request.session, 'modified'):
            request.session.modified = True

    follow_count = len(followed)
    tier_info = _get_tier_prices(pricing_config, follow_count)

    return JsonResponse({
        'success': True,
        'message': 'Follow recorded successfully!',
        'discount_unlocked': follow_count > 0,
        'follow_count': follow_count,
        'applied_discount': tier_info['applied_discount'],
        'starter_applied_discount': tier_info.get('starter_applied_discount', 0),
        'prof_applied_discount': tier_info.get('prof_applied_discount', 0),
        'starter_price': tier_info['starter_price'],
        'starter_base': tier_info['starter_base'],
        'starter_total': tier_info['starter_total'],
        'prof_price': tier_info['prof_price'],
        'prof_base': tier_info['prof_base'],
        'prof_total': tier_info['prof_total'],
        'followed_platforms': followed,
    })


@require_POST
@csrf_protect
def record_scratch_reveal(request):
    """Persist that the user revealed the starter/professional scratch price."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST
    plan_type = resolve_checkout_plan_slug(data.get('plan_type'))
    if plan_type not in ('starter', 'professional'):
        return JsonResponse({'success': False, 'message': 'Invalid plan.'}, status=400)
    request.session[_scratch_session_key(plan_type)] = True
    request.session.modified = True
    return JsonResponse({'success': True, 'plan_type': plan_type})


def exclusive_discount_status(request):
    """Get the current discount status and followed platforms."""
    agent_id = request.GET.get('agent_id')
    if not agent_id:
        return JsonResponse({'success': False, 'message': 'Missing agent_id'}, status=400)
    
    session_key = f'followed_platforms_{agent_id}'
    followed = request.session.get(session_key, [])
    discount_unlocked = len(followed) > 0
    
    from apps.home.models import SiteSetting
    exclusive_config = SiteSetting.get_value('exclusive_plan_config') or {}
    
    follow_count = len(followed)
    current_price = _exclusive_base_price(exclusive_config, follow_count, discount_unlocked)
        
    # Only heal the draft this session owns — this is a GET and must not let a
    # caller flip discount state on arbitrary draft ids.
    if discount_unlocked and str(agent_id) == str(request.session.get('current_draft_id') or ''):

        # Sync session state to database to heal any mismatched states
        from apps.agents.models import AgentDraft, UserPlanProgress
        try:
            draft = AgentDraft.objects.get(pk=agent_id)
            progress, _ = UserPlanProgress.objects.get_or_create(draft=draft, plan_key='exclusive_gamified')
            progress.discount_unlocked = True
            progress.save()
            logger.info(f"Healed and saved discount_unlocked=True for draft {draft.id}")
        except Exception as e:
            logger.error(f"Failed to heal UserPlanProgress in discount_status: {e}")

    return JsonResponse({
        'success': True,
        'discount_unlocked': discount_unlocked,
        'current_price': current_price,
        'followed_platforms': followed
    })



def _resolve_chooseplan_draft_id(request):
    """Restore choose-plan draft from session or the logged-in agent's email."""
    draft_id = request.session.get('current_draft_id')
    if draft_id:
        return draft_id
    if not request.user.is_authenticated:
        return None
    try:
        from apps.agents.services.account_auth import resolve_agent_for_user
        logged_in = resolve_agent_for_user(request.user)
    except Exception:
        return None
    if not logged_in:
        return None
    from apps.agents.models import AgentDraft
    draft = AgentDraft.objects.filter(email__iexact=logged_in.email).order_by('-updated_at').first()
    if draft:
        request.session['current_draft_id'] = draft.pk
        return draft.pk
    return None


def chooseplan(request):
    """Render the plan selection page."""
    if request.user.is_authenticated:
        from apps.agents.services.account_auth import resolve_agent_for_user, agent_can_access_dashboard
        try:
            logged_in_agent = resolve_agent_for_user(request.user)
        except Exception:
            logged_in_agent = None
        if logged_in_agent and agent_can_access_dashboard(logged_in_agent):
            return redirect('agents:agent_dashboard')
        elif request.user.is_staff or request.user.is_superuser:
            return redirect('agents:agent_dashboard')

    recovered_url = _recover_pending_razorpay_checkout(request)
    if recovered_url:
        return redirect(recovered_url)

    draft_id = _resolve_chooseplan_draft_id(request)

    if not draft_id:
        return redirect('agents:agent_registration')

    try:
        from apps.agents.models import AgentDraft
        agent = AgentDraft.objects.get(pk=draft_id)
    except AgentDraft.DoesNotExist:
        request.session.pop('current_draft_id', None)
        return redirect('agents:agent_registration')

    # ── Mark as CLAIM stage: user is now viewing plans ──────────────────────
    # This runs BEFORE any agent is created, so the draft entry in admin
    # pending registrations correctly shows CLAIM badge on next refresh.
    if (agent.registration_step or 1) < 2:
        try:
            agent.registration_step = 2
            agent.save(update_fields=['registration_step'])
            RegistrationActivityLog.log(
                RegistrationActivityLog.EVENT_CLAIM_BUTTON,
                draft_id=agent.pk,
                request=request,
                email=agent.email or '',
            )
        except Exception as _e:
            import logging as _lg; _lg.getLogger(__name__).warning(f'CLAIM stage update failed: {_e}')
    # ─────────────────────────────────────────────────────────────────────────

    _clear_scratch_reveal_session(request)

    # Load site settings pricing config from DB only
    pricing_config = SiteSetting.get_value('pricing_config', _DEFAULT_PRICING)
    if not isinstance(pricing_config, dict):
        pricing_config = dict(_DEFAULT_PRICING)
    pricing_config.setdefault('choose_plan_heading', _DEFAULT_PRICING['choose_plan_heading'])
    comparison_price_mode = (pricing_config.get('comparison_price_display') or 'original').strip().lower()
    if comparison_price_mode not in ('original', 'discounted'):
        comparison_price_mode = 'original'

    starter_cfg = pricing_config.get('starter', _DEFAULT_PRICING['starter'])
    prof_cfg = pricing_config.get('professional', _DEFAULT_PRICING['professional'])
    if not starter_cfg or not prof_cfg:
        return render(request, '500.html', status=500)

    trial_config = SiteSetting.get_value('trial_plan_config')
    if not trial_config or not isinstance(trial_config, dict) or not trial_config.get('price'):
        trial_config = {'price': 1, 'is_active': True, 'duration_days': 30}

    trial_active = trial_config.get('is_active', True)
    trial_base_price = float(trial_config.get('price', 1))
    trial_duration = trial_config.get('duration_days', 30)

    # Promo codes
    applied_promo_code = request.session.get('applied_promo_code') or ''
    applied_promo_code = applied_promo_code.strip().upper()

    has_promo = False
    has_free_trial_promo = False
    has_starter_promo = False
    has_prof_promo = False

    promo_obj = None

    if applied_promo_code:
        try:
            promo_obj = PromoCode.objects.filter(code=applied_promo_code).first()
            if promo_obj and promo_obj.is_valid():
                has_promo = True
            else:
                promo_obj = None
        except Exception:
            pass

    if has_promo and promo_obj and promo_obj.is_free_trial_code():
        has_free_trial_promo = True

    # Calculate Trial plan price
    if has_free_trial_promo and promo_obj:
        if promo_obj.trial_price_override is not None:
            trial_base_price = float(promo_obj.trial_price_override)
        if float(promo_obj.discount_value) > 0:
            discount = promo_obj.calculate_discount(trial_base_price)
            trial_base_price = max(0.0, trial_base_price - discount)
        if promo_obj.trial_duration_days:
            trial_duration = promo_obj.trial_duration_days

    trial_final = trial_base_price + (trial_base_price * 0.18)

    # Scratch & Social Discounts
    starter_scratch_enabled = _is_scratch_enabled(starter_cfg)
    prof_scratch_enabled = _is_scratch_enabled(prof_cfg)
    scratch_card_enabled = starter_scratch_enabled or prof_scratch_enabled
    social_discount_active = pricing_config.get('social_discount_active', True)
    social_discount_amount = float(pricing_config.get('social_discount_amount', 200) or 200)
    social_links = pricing_config.get('social_links', _DEFAULT_PRICING['social_links'])
    follow_tiers = pricing_config.get('follow_tiers', _DEFAULT_PRICING['follow_tiers'])

    session_key = f'followed_platforms_{draft_id}'
    followed = request.session.get(session_key, [])
    follow_count = len(followed)
    has_social_discount = social_discount_active and follow_count > 0

    tier_info = _get_tier_prices(pricing_config, follow_count)
    starter_full = tier_info['starter_full']
    starter_discounted = tier_info['starter_price']
    starter_base = tier_info['starter_base']
    starter_gst = tier_info['starter_gst']
    starter_final = tier_info['starter_total']

    if not has_free_trial_promo and has_promo and promo_obj and promo_obj.is_valid('starter'):
        starter_base = int(round(max(0.0, starter_full - promo_obj.calculate_discount(starter_full))))
        starter_gst = round(starter_base * 0.18, 2)
        starter_final = int(round(starter_base + starter_gst))
        has_starter_promo = True
        starter_scratch_enabled = False

    starter_discount_percent = 0
    if starter_full > 0 and starter_base < starter_full:
        starter_discount_percent = round((1 - (starter_base / starter_full)) * 100)

    prof_full = tier_info['prof_full']
    prof_discounted = tier_info['prof_price']
    prof_base = tier_info['prof_base']
    prof_gst = tier_info['prof_gst']
    prof_final = tier_info['prof_total']

    if not has_free_trial_promo and has_promo and promo_obj and promo_obj.is_valid('professional'):
        prof_base = int(round(max(0.0, prof_full - promo_obj.calculate_discount(prof_full))))
        prof_gst = round(prof_base * 0.18, 2)
        prof_final = int(round(prof_base + prof_gst))
        has_prof_promo = True
        prof_scratch_enabled = False

    scratch_card_enabled = starter_scratch_enabled or prof_scratch_enabled

    prof_discount_percent = 0
    if prof_full > 0 and prof_base < prof_full:
        prof_discount_percent = round((1 - (prof_base / prof_full)) * 100)

    # Apply Referral Championship 50% Campaign Offer if candidate is referred AND promo code does not give a lower price
    championship_ref_id = request.session.get('championship_ref_id')
    if championship_ref_id:
        try:
            from apps.referral_championship.models import ChampionshipCampaign
            champ = ChampionshipCampaign.get_current()
            champ_pricing = champ.pricing_config or {}
            dig_camp = float(champ_pricing.get('digital', {}).get('campaign_price', 999))
            prof_camp = float(champ_pricing.get('professional', {}).get('campaign_price', 4999))

            if not has_starter_promo or starter_final > dig_camp:
                starter_final = dig_camp
                starter_base = round(dig_camp / 1.18, 2)
                starter_gst = round(starter_final - starter_base, 2)
                starter_discount_percent = 50

            if not has_prof_promo or prof_final > prof_camp:
                prof_final = prof_camp
                prof_base = round(prof_camp / 1.18, 2)
                prof_gst = round(prof_final - prof_base, 2)
                prof_discount_percent = 50
        except Exception:
            pass

    if comparison_price_mode == 'discounted':
        compare_starter_price = int(starter_base)
        compare_prof_price = int(prof_base)
    else:
        compare_starter_price = int(round(starter_full))
        compare_prof_price = int(round(prof_full))

    compare_starter_show_strike = (
        comparison_price_mode == 'discounted' and compare_starter_price < int(round(starter_full))
    )
    compare_prof_show_strike = (
        comparison_price_mode == 'discounted' and compare_prof_price < int(round(prof_full))
    )

    starter_name = PLAN_LABELS['starter']
    starter_desc = starter_cfg.get('description', 'Perfect for New Agents')
    starter_scratch_text = (starter_cfg.get('scratch_text') or 'SCRATCH').strip() or 'SCRATCH'
    prof_name = PLAN_LABELS['professional']
    prof_desc = prof_cfg.get('description', 'For Established Professionals')
    prof_scratch_text = (prof_cfg.get('scratch_text') or 'SCRATCH').strip() or 'SCRATCH'

    trial_gst = round(trial_base_price * 0.18, 2)

    # Fetch Gamification Config
    exclusive_config = SiteSetting.get_value('exclusive_plan_config') or {}
    is_exclusive_active = exclusive_config.get('is_active', False)
    session_key = f'followed_platforms_{draft_id}'
    followed = request.session.get(session_key, [])
    follow_count = len(followed)
    discount_unlocked = follow_count > 0
    
    exc_strikeout = float(exclusive_config.get('strikeout_price', 6999))
    exc_base = float(exclusive_config.get('base_price', 1999))
    exc_discounted = _exclusive_base_price(exclusive_config, follow_count, discount_unlocked)
    
    if exc_strikeout > 0 and exc_base < exc_strikeout:
        exclusive_config['before_discount_val'] = f"{int(round((exc_strikeout - exc_base) / exc_strikeout * 100))}%"
    else:
        exclusive_config['before_discount_val'] = "0%"
        
    if exc_base > 0 and exc_discounted < exc_base:
        exclusive_config['after_discount_val'] = f"{int(round((exc_base - exc_discounted) / exc_base * 100))}%"
    else:
        exclusive_config['after_discount_val'] = "0%"

    # Prepare Gamification UI Context Variables
    default_features = [
        {'name': 'Permanent<br>Website', 'icon': 'fa-globe', 'color': '#16a34a', 'bg_color': '#f0fdf4'},
        {'name': 'Digital<br>Card', 'icon': 'fa-id-card-clip', 'color': '#6d28d9', 'bg_color': '#f3e8ff'},
        {'name': 'Licensed<br>Badge', 'icon': 'fa-shield-halved', 'color': '#f59e0b', 'bg_color': '#fffbeb'},
        {'name': 'Call &<br>WhatsApp', 'icon': 'fa-phone', 'color': '#16a34a', 'bg_color': '#f0fdf4'},
        {'name': 'Customer<br>Reviews', 'icon': 'fa-star', 'color': '#6d28d9', 'bg_color': '#f3e8ff'},
        {'name': 'Product<br>Showcase', 'icon': 'fa-store', 'color': '#3b82f6', 'bg_color': '#eff6ff'}
    ]
    premium_features = exclusive_config.get('premium_features', None)
    if premium_features is None:
        premium_features = default_features
        
    social_links = exclusive_config.get('social_links', [])
    social_labels = {
        'instagram': 'Instagram',
        'facebook': 'Facebook',
        'x': 'X',
        'twitter': 'X',
        'linkedin': 'LinkedIn',
        'youtube': 'YouTube',
        'whatsapp': 'WhatsApp',
    }
    for link in social_links:
        platform = (link.get('platform') or '').lower()
        link['platform_key'] = platform
        link['label'] = social_labels.get(platform, (link.get('platform') or '').title())
        user_icon = (link.get('icon') or '').strip()
        if user_icon.startswith('fa-'):
            link['iconClass'] = user_icon
        elif platform in ('x', 'twitter'):
            link['iconClass'] = 'fa-x-twitter'
        elif platform == 'linkedin':
            link['iconClass'] = 'fa-linkedin-in'
        elif platform == 'facebook':
            link['iconClass'] = 'fa-facebook-f'
        elif platform == 'youtube':
            link['iconClass'] = 'fa-youtube'
        else:
            link['iconClass'] = 'fa-instagram'

    checkout_label = (exclusive_config.get('checkout_btn_text') or 'Claim Now').strip()
    if checkout_label.upper() in ('BUY', 'CLAIM OFFER'):
        checkout_label = 'Claim Now'
    exclusive_config['checkout_btn_text'] = checkout_label

    title_prefix = (exclusive_config.get('title_prefix') or 'Surprise!!!!').strip()
    if title_prefix in ('Surprise!', 'Surprise'):
        title_prefix = 'Surprise!!!!'
    exclusive_config['title_prefix'] = title_prefix

    gift_subtitle = (exclusive_config.get('gift_subtitle') or '').strip()
    if gift_subtitle in (
        '',
        'For a limited time, get our best deal.',
        'Follow our social handles to reveal your secret discounted price.',
    ):
        exclusive_config['gift_subtitle'] = 'Follow us on Social Media...'

    try:
        total_seats = int(exclusive_config.get('total_seats') or 1000)
    except (TypeError, ValueError):
        total_seats = 1000
    try:
        claimed_seats = int(exclusive_config.get('base_claimed_seats') or 874)
    except (TypeError, ValueError):
        claimed_seats = 874
    spots_left = max(0, total_seats - claimed_seats)

    def _format_urgency(template, fallback):
        text = template or fallback
        try:
            return text.format(
                total_seats=total_seats,
                claimed_seats=claimed_seats,
                spots_left=spots_left,
            )
        except (KeyError, ValueError, IndexError):
            return text

    urgency_line_1 = _format_urgency(
        exclusive_config.get('urgency_line_1'),
        '🔥 Hurry! Offer valid only for the first {total_seats} users!',
    )
    urgency_line_2 = _format_urgency(
        exclusive_config.get('urgency_line_2'),
        '🔥 {claimed_seats}/{total_seats} Claimed',
    )

    scratch_popup = _normalize_scratch_popup(pricing_config.get('scratch_popup'))

    context = {
        'draft': agent,  # Pass agent as draft to avoid template changes
        'agent': agent,
        'pricing_config': pricing_config,
        'scratch_card_enabled': scratch_card_enabled,
        'starter_scratch_enabled': starter_scratch_enabled,
        'prof_scratch_enabled': prof_scratch_enabled,
        'starter_scratch_revealed': False,
        'prof_scratch_revealed': False,
        'starter_full_total': _gst_bundle_from_base(starter_full)[2],
        'prof_full_total': _gst_bundle_from_base(prof_full)[2],
        'social_discount_active': social_discount_active,
        'social_discount_amount': social_discount_amount,
        'social_links': social_links,
        'follow_tiers': follow_tiers,
        'follow_tiers_json': json.dumps(follow_tiers),
        'has_social_discount': has_social_discount,
        'followed_platforms': followed,
        'trial_config': trial_config,
        'trial_active': trial_active,
        'trial_base_price': trial_base_price,
        'trial_gst': trial_gst,
        'trial_final': trial_final,
        'trial_duration': trial_duration,
        
        'starter_name': starter_name,
        'starter_desc': starter_desc,
        'starter_scratch_text': starter_scratch_text,
        'starter_full': starter_full,
        'starter_discounted': starter_discounted,
        'starter_final': starter_final,
        'starter_gst': starter_gst,
        'starter_base': starter_base,
        'starter_scratch_price': tier_info['starter_scratch_price'],
        'starter_discount_percent': starter_discount_percent,
        
        'prof_name': prof_name,
        'prof_desc': prof_desc,
        'prof_scratch_text': prof_scratch_text,
        'prof_full': prof_full,
        'prof_discounted': prof_discounted,
        'prof_final': prof_final,
        'prof_gst': prof_gst,
        'prof_base': prof_base,
        'prof_scratch_price': tier_info['prof_scratch_price'],
        'prof_discount_percent': prof_discount_percent,

        'applied_promo_code': applied_promo_code,
        'promo_obj': promo_obj,
        'has_promo': has_promo,
        'has_free_trial_promo': has_free_trial_promo,
        'has_starter_promo': has_starter_promo,
        'has_prof_promo': has_prof_promo,

        'is_upgrade_flow': False,
        'exclusive_config': exclusive_config,
        'is_exclusive_active': is_exclusive_active,
        'discount_unlocked': discount_unlocked,
        'premiumFeatures': premium_features,
        'spots_left': spots_left,
        'urgency_line_1': urgency_line_1,
        'urgency_line_2': urgency_line_2,
        'starter_plan_features': _STARTER_PLAN_UI_FEATURES,
        'professional_plan_features': _PROFESSIONAL_PLAN_UI_FEATURES,
        'plan_comparison_rows': _PLAN_COMPARISON_ROWS,
        'comparison_price_mode': comparison_price_mode,
        'compare_starter_price': compare_starter_price,
        'compare_prof_price': compare_prof_price,
        'compare_starter_show_strike': compare_starter_show_strike,
        'compare_prof_show_strike': compare_prof_show_strike,
        'scratch_popup': scratch_popup,
        'scratch_popup_json': json.dumps(scratch_popup),
        'hide_site_nav': True,
        'hide_footer': True,
        'hide_chatbot': True,
    }

    return render(request, 'agents/plans.html', context)



def create_agent_from_draft(draft, plan_type, plan_name, status='pending_payment'):
    import re
    import time
    from decimal import Decimal, InvalidOperation
    from django.core.files.storage import default_storage
    from django.utils.text import slugify
    from apps.agents.models import Agent, AgentProfile, AgentInsuranceSegment, AgentPerformanceStat

    def _claim_amount_from_draft(raw):
        if not raw:
            return Decimal('0')
        cleaned = re.sub(r'[^\d.]', '', str(raw).strip())
        if not cleaned:
            return Decimal('0')
        try:
            return Decimal(cleaned) * Decimal('100000')
        except InvalidOperation:
            return Decimal('0')

    now = timezone.now()
    
    agent, created = Agent.objects.get_or_create(
        email=draft.email,
        defaults={
            'fullname': draft.fullname,
            'mobile': draft.mobile,
            'user_types': ['insurance_agent'],
            'insurance_companies': draft.insurance_companies or [],
            'experience_range': draft.experience_range or '',
            'client_base': draft.client_base or '',
            'registration_step': 2,
            'status': status,
            'plan_type': plan_type,
            'agent_pincode': draft.agent_pincode,
            'email_verified_at': now,
            'distributor_id': getattr(draft, 'distributor_id', None),
            'sub_distributor_id': getattr(draft, 'sub_distributor_id', None),
            'referred_by_code': getattr(draft, 'referred_by_code', '') or '',
        }
    )
    
    if not created:
        agent.fullname = draft.fullname
        agent.mobile = draft.mobile
        agent.insurance_companies = draft.insurance_companies or []
        agent.experience_range = draft.experience_range or ''
        agent.client_base = draft.client_base or ''
        agent.status = status
        agent.plan_type = plan_type
        agent.agent_pincode = draft.agent_pincode
        agent.email_verified_at = now
        if getattr(draft, 'distributor_id', None):
            agent.distributor_id = draft.distributor_id
        if getattr(draft, 'sub_distributor_id', None):
            agent.sub_distributor_id = draft.sub_distributor_id
        if getattr(draft, 'referred_by_code', None):
            agent.referred_by_code = draft.referred_by_code
        agent.save()

    # ── Event: PENDING_FOR_REGISTRATION ─────────────────────────────────────
    if status == 'pending_payment':
        RegistrationActivityLog.log(
            RegistrationActivityLog.EVENT_PENDING_REGISTRATION,
            agent=agent,
            draft_id=draft.pk,
            extra_details={
                'plan_type': plan_type,
                'plan_name': plan_name,
                'draft_email': draft.email,
                'created_new': created,
            },
        )

    # Create insurance segments (delete + insert like PHP)
    AgentInsuranceSegment.objects.filter(agent=agent).delete()
    for seg in (draft.segments or []):
        AgentInsuranceSegment.objects.create(agent=agent, segment_type=seg)
    
    # Write registration_draft JSON (matching PHP Step 2)
    agent.registration_draft = {
        'license_number': draft.license_number or '',
        'pan_number': draft.pan_number or '',
        'software_name': draft.software_name or '',
        'portfolio_breakdown': {
            'life_insurance': draft.life_insurance or 0,
            'health_insurance': draft.health_insurance or 0,
            'general_insurance': draft.general_insurance or 0,
            'motor': draft.motor or 0,
        },
        'desired_services': draft.desired_services or [],
    }
    agent.save(update_fields=['registration_draft', 'updated_at'])
    
    profile, p_created = AgentProfile.objects.get_or_create(
        agent=agent,
        defaults={
            'license_number': draft.license_number or '',
            'license_valid_till': draft.license_valid_till,
            'arn_number': draft.arn_number or '',
            'euin_number': draft.euin_number or '',
            'investment_valid_till': draft.investment_valid_till,
            'investment_types': draft.investment_types or [],
            'pan_number': draft.pan_number or '',
            'software_name': draft.software_name or '',
            'portfolio_breakdown': {
                'life_insurance': draft.life_insurance or 0,
                'health_insurance': draft.health_insurance or 0,
                'general_insurance': draft.general_insurance or 0,
                'motor': draft.motor or 0,
            },
            'desired_services': draft.desired_services or [],
            'whatsapp': draft.whatsapp or '',
            'address': draft.address or '',
            'state': draft.state or '',
            'service_pincodes': [draft.agent_pincode] if draft.agent_pincode else [],
        }
    )
    if not p_created:
        profile.license_number = draft.license_number or ''
        profile.license_valid_till = draft.license_valid_till
        profile.arn_number = draft.arn_number or ''
        profile.euin_number = draft.euin_number or ''
        profile.investment_valid_till = draft.investment_valid_till
        profile.investment_types = draft.investment_types or []
        profile.pan_number = draft.pan_number or ''
        profile.software_name = draft.software_name or ''
        profile.portfolio_breakdown = {
            'life_insurance': draft.life_insurance or 0,
            'health_insurance': draft.health_insurance or 0,
            'general_insurance': draft.general_insurance or 0,
            'motor': draft.motor or 0,
        }
        profile.desired_services = draft.desired_services or []
        profile.whatsapp = draft.whatsapp or profile.whatsapp or ''
        profile.address = draft.address or profile.address or ''
        profile.state = draft.state or profile.state or ''
        if draft.agent_pincode:
            profile.service_pincodes = [draft.agent_pincode]
        profile.save()

    if draft.slug:
        base_slug = slugify(draft.slug) or slugify(draft.fullname) or 'agent'
        unique_slug = base_slug
        count = 1
        while AgentProfile.objects.filter(slug=unique_slug).exclude(pk=profile.pk).exists():
            unique_slug = f'{base_slug}-{count}'
            count += 1
        profile.slug = unique_slug
        profile.save(update_fields=['slug', 'updated_at'])

    if draft.languages:
        langs = draft.languages
        if isinstance(langs, list):
            profile.languages = ', '.join(str(l).strip() for l in langs if str(l).strip())
        elif langs:
            profile.languages = str(langs)
        profile.save(update_fields=['languages', 'updated_at'])

    if draft.about:
        profile.career_highlights = draft.about
        profile.save(update_fields=['career_highlights', 'updated_at'])

    if draft.photo:
        ext = os.path.splitext(draft.photo.name)[1].lower() or '.jpg'
        file_name = f'app/public/profile/agent_{agent.id}_{int(time.time())}{ext}'
        saved_path = default_storage.save(file_name, draft.photo)
        profile.profile_photo_path = saved_path
        profile.save(update_fields=['profile_photo_path', 'updated_at'])

    claims_settled = int(draft.claims_settled or 0)
    claims_amount = _claim_amount_from_draft(draft.claim_amount)
    if claims_settled or claims_amount:
        AgentPerformanceStat.objects.update_or_create(
            agent=agent,
            defaults={
                'claims_settled': claims_settled,
                'claims_processed': claims_settled,
                'claims_amount': claims_amount,
            },
        )
    
    # Clear registration_draft after committing to profile (matching PHP)
    agent.registration_draft = None
    agent.save(update_fields=['registration_draft', 'updated_at'])
    
    return agent


def create_or_link_django_user(agent, plain_password=None):
    from apps.agents.services.account_auth import create_or_link_django_user as _create_or_link
    return _create_or_link(agent, plain_password=plain_password)


def _isolated(label, fn):
    """Run a best-effort side effect of payment activation in its own savepoint.

    These steps used to run bare inside the activation transaction behind a
    try/except. A DB error there (e.g. referral code insert failing) marked the
    whole transaction for rollback, so the payment silently stayed 'pending'
    while the user was told it succeeded. A nested atomic() confines the
    failure to its own savepoint.
    """
    from django.db import transaction
    try:
        with transaction.atomic():
            return fn()
    except Exception as err:
        logger.warning('%s failed (payment activation unaffected): %s', label, err)
        return None


def _increment_promo_usage(promo_code):
    if not promo_code:
        return
    from django.db.models import F
    PromoCode.objects.filter(code=promo_code).update(times_used=F('times_used') + 1)


def _credit_referral_conversion(agent):
    """Mark the referral as converted and grant the 5-referral reward."""
    if not agent or not agent.referred_by_code:
        return
    from apps.admin_panel.models.referral_code import ReferralCode
    from apps.admin_panel.models.referral_usage import ReferralUsage

    ref_code_obj = ReferralCode.objects.filter(code=agent.referred_by_code).first()
    if not ref_code_obj:
        return
    usage, u_created = ReferralUsage.objects.get_or_create(
        referral_code=ref_code_obj,
        referred_agent_id=agent.id,
        defaults={'status': 'converted', 'signed_up_at': timezone.now()}
    )
    if not u_created and usage.status != 'converted':
        usage.status = 'converted'
        usage.save()

    actual_conversions = ReferralUsage.objects.filter(
        referral_code=ref_code_obj,
        status='converted'
    ).count()
    ref_code_obj.total_referrals = actual_conversions
    ref_code_obj.save()

    if actual_conversions >= 5:
        referring_agent = Agent.objects.filter(pk=ref_code_obj.agent_id).first()
        if referring_agent and referring_agent.plan_type == 'free_trial':
            referring_agent.referral_reward_type = 'pro_plan_1rs'
            referring_agent.referral_reward_earned_at = timezone.now()
            referring_agent.save()


def _ensure_referral_code(agent):
    from apps.admin_panel.models.referral_code import ReferralCode
    if not ReferralCode.objects.filter(agent=agent).exists():
        ReferralCode.generateForAgent(agent)


def _championship_qualification(agent, subscription):
    from apps.referral_championship.services.qualification_service import process_championship_qualification
    process_championship_qualification(agent, subscription)


def _order_plan_slug(subscription, agent):
    """Plan to activate for a paid order.

    Falls back to the plan the agent was priced for at checkout (agent.plan_type
    is set when the order is created) — never to 'professional', which granted
    an upgrade whenever a plan display name did not parse.
    """
    from apps.agents.services.feature_unlock import normalize_plan_slug, PLAN_SLUGS
    slug = plan_slug_from_name(getattr(subscription, 'selected_plan', '') or '')
    if slug:
        return slug
    current = normalize_plan_slug(getattr(agent, 'plan_type', '') or '')
    return current if current in PLAN_SLUGS else 'starter'


def verify_and_activate_pending_payment(agent):
    """
    Directly query Razorpay to verify if the pending order has a captured/authorized payment,
    and activate the subscription/registration atomically and idempotently.
    """
    from django.utils import timezone
    from django.db import transaction
    from apps.agents.models import AgentSubscription, PromoCode
    from apps.home.models import SiteSetting

    from apps.agents.services.account_auth import agent_has_completed_payment, is_real_razorpay_id

    if agent_has_completed_payment(agent):
        logger.info(
            '[verify_and_activate_pending_payment] Verified payment already exists for agent #%s.',
            agent.id,
        )
        return True

    subscription = AgentSubscription.objects.filter(
        agent=agent,
        payment_status__in=['pending', 'failed'],
    ).order_by('-created_at').first()
    if not subscription or not subscription.razorpay_order_id:
        logger.info(f"[verify_and_activate_pending_payment] No pending/failed subscription or Razorpay Order ID for {agent.email}")
        return False
    if not is_real_razorpay_id(subscription.razorpay_order_id, 'order_'):
        logger.info(
            '[verify_and_activate_pending_payment] Skipping mock order %s',
            subscription.razorpay_order_id,
        )
        return False

    try:
        client = razorpay_client()
        if client is None:
            logger.error("[verify_and_activate_pending_payment] Razorpay keys not configured.")
            return False
        payments = client.order.payments(subscription.razorpay_order_id)
    except Exception as err:
        logger.error(f"[verify_and_activate_pending_payment] Razorpay API call failed: {err}")
        return False

    successful_payment = None
    if payments and 'items' in payments:
        for item in payments['items']:
            if item.get('status') in ('captured', 'authorized'):
                successful_payment = item
                break

    if not successful_payment:
        logger.info(f"[verify_and_activate_pending_payment] No captured/authorized payments found for Order {subscription.razorpay_order_id}")
        return False

    paid_amount_paise = successful_payment.get('amount')
    expected_amount_paise = _expected_amount_paise(subscription.registration_amount)
    if not _paise_amounts_match(paid_amount_paise, expected_amount_paise):
        logger.critical(
            f"[verify_and_activate_pending_payment] Price tampering check failed! "
            f"Paid: {paid_amount_paise}, Expected: {expected_amount_paise}"
        )
        return False

    try:
        with transaction.atomic():
            # Locked subscription retrieve
            subscription = AgentSubscription.objects.select_for_update().get(pk=subscription.pk)
            if subscription.payment_status == 'completed':
                return True

            plan_type = _order_plan_slug(subscription, agent)
            is_trial = plan_type == 'free_trial'
            is_upgrade = _is_plan_upgrade_payment(agent, subscription.razorpay_order_id)

            trial_config = SiteSetting.get_value('trial_plan_config', {'duration_days': 30})
            trial_days = int(trial_config.get('duration_days', 30))
            sub_expiry = timezone.now() + timezone.timedelta(days=365)

            if is_trial:
                agent.status = 'active'
                agent.plan_type = 'free_trial'
                agent.trial_ends_at = timezone.now() + timezone.timedelta(days=trial_days)
                upgrade_discount = SiteSetting.get_value('trial_upgrade_discount', 20)
                agent.upgrade_discount_percent = int(upgrade_discount)
                sub_expiry = timezone.now() + timezone.timedelta(days=trial_days)
            elif is_upgrade:
                agent.plan_type = plan_type
                if agent.status in ('pending_payment', 'incomplete', 'pending_accounts_payment'):
                    agent.status = 'pending_approval'
            else:
                agent.status = 'pending_approval'
                agent.plan_type = plan_type

            agent.registration_step = 2
            agent.save()

            subscription.payment_status = 'completed'
            subscription.status = 'active'
            subscription.razorpay_payment_id = successful_payment.get('id')
            subscription.razorpay_signature = successful_payment.get('signature') or 'direct_verification'
            subscription.starts_at = timezone.now()
            subscription.expires_at = sub_expiry
            subscription.save()
            _deactivate_superseded_subscriptions(agent, subscription.pk)

            # Best-effort side effects, each in its own savepoint.
            _isolated('[verify_and_activate_pending_payment] Promo usage increment',
                      lambda: _increment_promo_usage(subscription.promo_code))
            _isolated('[verify_and_activate_pending_payment] Referral credit conversion',
                      lambda: _credit_referral_conversion(agent))
            _isolated('[verify_and_activate_pending_payment] Championship qualification hook',
                      lambda: _championship_qualification(agent, subscription))
            _isolated('[verify_and_activate_pending_payment] Referral code generation',
                      lambda: _ensure_referral_code(agent))

            # Link user
            user = create_or_link_django_user(agent)

            queue_invoice_and_welcome(agent.id, subscription.id)

            logger.info(f"[verify_and_activate_pending_payment] Successfully activated agent {agent.email} via direct Razorpay query.")
            return True
    except Exception as db_err:
        logger.error(f"[verify_and_activate_pending_payment] Database activation transaction failed: {db_err}")
        return False



# Names that plan_slug_from_name() maps back to the same slug.
_PAID_PLAN_NAMES = {
    'starter': PLAN_LABELS['starter'],
    'professional': PLAN_LABELS['professional'],
}


@require_POST
@csrf_protect
def agent_register_complete(request):
    """
    Prepare order or complete registration.
    """
    try:
        return _agent_register_complete_impl(request)
    except Exception:
        logger.exception('agent_register_complete failed')
        return JsonResponse({
            'success': False,
            'message': 'Unable to start payment right now. Please try again.',
        })


def _agent_register_complete_impl(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    raw_plan_type = data.get('plan_type')
    client_plan_name = data.get('plan_name')
    plan_type = resolve_checkout_plan_slug(raw_plan_type, client_plan_name)
    # plan_name is stored as subscription.selected_plan and later decides which
    # plan gets activated, so it must name the plan being priced here. The
    # branches below fill it from server config; a client name is only kept
    # when it resolves to the same plan (see below).
    plan_name = None
    if not plan_type:
        logger.error(f"Invalid plan selected. plan_type received: {repr(raw_plan_type)}")
        return JsonResponse({'success': False, 'message': 'Invalid plan selected.'}, status=400)

    draft_id = request.session.get('current_draft_id')
    if not draft_id:
        return JsonResponse({'success': False, 'message': 'Session expired. Please start over.'}, status=400)

    try:
        draft = AgentDraft.objects.get(pk=draft_id)
    except AgentDraft.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Registration record not found.'}, status=404)

    # Calculate pricing from DB only — no static fallback
    pricing_config = SiteSetting.get_value('pricing_config')
    if not pricing_config or not isinstance(pricing_config, dict):
        return JsonResponse({'success': False, 'message': 'Server configuration error.'}, status=500)

    starter_cfg = pricing_config.get('starter')
    prof_cfg = pricing_config.get('professional')
    if not starter_cfg or not prof_cfg or not starter_cfg.get('full_price') or not prof_cfg.get('full_price'):
        return JsonResponse({'success': False, 'message': 'Server configuration error.'}, status=500)

    trial_config = SiteSetting.get_value('trial_plan_config')
    if not trial_config or not isinstance(trial_config, dict) or not trial_config.get('price'):
        return JsonResponse({'success': False, 'message': 'Server configuration error.'}, status=500)

    applied_promo_code = (request.session.get('applied_promo_code') or '').strip().upper()
    has_promo = bool(applied_promo_code)
    has_free_trial_promo = False

    promo_obj = None

    if applied_promo_code:
        try:
            promo_obj = PromoCode.objects.filter(code=applied_promo_code).first()
        except Exception:
            pass

    if promo_obj and promo_obj.is_free_trial_code() and promo_obj.is_valid():
        has_free_trial_promo = True

    trial_base_price = float(trial_config['price'])
    starter_full = float(starter_cfg['full_price'])
    prof_full = float(prof_cfg['full_price'])
    
    if plan_type == 'free_trial':
        if has_free_trial_promo and promo_obj:
            if promo_obj.trial_price_override is not None:
                trial_base_price = float(promo_obj.trial_price_override)
            if float(promo_obj.discount_value) > 0:
                trial_base_price = max(0.0, trial_base_price - promo_obj.calculate_discount(trial_base_price))
        total_amount = trial_base_price + (trial_base_price * 0.18)
        plan_name = plan_name or f"Trial Plan ({trial_config.get('duration_days', 30)} Days)"
    elif plan_type == 'exclusive':
        exclusive_config = SiteSetting.get_value('exclusive_plan_config') or {}
        
        from apps.agents.models import UserPlanProgress
        session_key = f'followed_platforms_{draft_id}'
        followed = request.session.get(session_key, [])
        follow_count = len(followed)
        discount_unlocked = follow_count > 0
        progress = UserPlanProgress.objects.filter(draft=draft, plan_key='exclusive_gamified').first()
        if progress and progress.discount_unlocked:
            discount_unlocked = True
            
        base_price = _exclusive_base_price(exclusive_config, follow_count, discount_unlocked)
        total_amount = round(base_price + round(base_price * 0.18, 2), 2)
        plan_name = plan_name or exclusive_config.get('name') or 'Exclusive Plan'
        logger.info(f"Exclusive Checkout: discount_unlocked={discount_unlocked}, follow_count={follow_count}, base_price={base_price}, total_amount={total_amount}")
    elif plan_type == 'starter':
        session_key = f'followed_platforms_{draft_id}'
        followed = request.session.get(session_key, [])
        follow_count = len(followed)
        checkout_promo = promo_obj if (not has_free_trial_promo and has_promo) else None
        total_amount = _checkout_total_for_plan(
            pricing_config, follow_count, 'starter', request, data, checkout_promo,
        )
        if request.session.get('championship_ref_id') and not checkout_promo:
            try:
                from apps.referral_championship.models import ChampionshipCampaign
                champ = ChampionshipCampaign.get_current()
                champ_pricing = champ.pricing_config or {}
                total_amount = float(champ_pricing.get('digital', {}).get('campaign_price', 999))
            except Exception:
                pass
        plan_name = PLAN_LABELS['starter']
        logger.info(
            'Starter checkout: full=%s displayed=%s follow=%s total=%s',
            starter_full, data.get('displayed_total'), follow_count, total_amount,
        )
    else:
        session_key = f'followed_platforms_{draft_id}'
        followed = request.session.get(session_key, [])
        follow_count = len(followed)
        checkout_promo = promo_obj if (not has_free_trial_promo and has_promo) else None
        total_amount = _checkout_total_for_plan(
            pricing_config, follow_count, 'professional', request, data, checkout_promo,
        )
        if request.session.get('championship_ref_id') and not checkout_promo:
            try:
                from apps.referral_championship.models import ChampionshipCampaign
                champ = ChampionshipCampaign.get_current()
                champ_pricing = champ.pricing_config or {}
                total_amount = float(champ_pricing.get('professional', {}).get('campaign_price', 4999))
            except Exception:
                pass
        plan_name = PLAN_LABELS['professional']
        logger.info(
            'Professional checkout: full=%s displayed=%s follow=%s total=%s',
            prof_full, data.get('displayed_total'), follow_count, total_amount,
        )

    if plan_type in _PAID_PLAN_NAMES:
        plan_name = _PAID_PLAN_NAMES[plan_type]

    total_amount = _to_money(total_amount)
    amount_paise = _to_paise(total_amount)
    razorpay_order_id, mock_checkout = create_checkout_order(
        amount_paise,
        f'agent_draft_{draft.pk}_{int(time.time())}',
        request,
    )

    # Strict Production Guard: If order creation fails for a paid plan, prevent bypass
    if not razorpay_order_id and amount_paise > 0:
        return JsonResponse({
            'success': False,
            'message': gateway_failure_message(),
        })

    from django.db import transaction
    from apps.agents.models import Agent, AgentSubscription, Invoice

    instant_complete = False
    try:
        with transaction.atomic():
            # Create/get Agent record from DB
            agent = create_agent_from_draft(draft, plan_type, plan_name, status='pending_payment')
            
            # Capture distributor/referral binding
            sub_dist_id = request.session.get('sub_distributor_id') or getattr(draft, 'sub_distributor_id', None)
            if sub_dist_id:
                agent.sub_distributor_id = sub_dist_id

            dist_id_from_session = request.session.get('distributor_id') or getattr(draft, 'distributor_id', None)
            if dist_id_from_session:
                agent.distributor_id = dist_id_from_session
                from apps.admin_panel.models.referral_code import ReferralCode
                ref_obj = ReferralCode.objects.filter(distributor_id=dist_id_from_session, is_active=True).first()
                if ref_obj:
                    agent.referred_by_code = ref_obj.code
                if sub_dist_id:
                    from apps.distributors.models import SubDistributor
                    sub_dist_obj = SubDistributor.objects.filter(id=sub_dist_id).first()
                    if sub_dist_obj:
                        agent.referred_by_code = sub_dist_obj.code
                agent.save()
                # ── Event: DISTRIBUTION ──────────────────────────────────
                RegistrationActivityLog.log(
                    RegistrationActivityLog.EVENT_DISTRIBUTION,
                    request=request,
                    agent=agent,
                    draft_id=draft.pk,
                    extra_details={
                        'distributor_id': dist_id_from_session,
                        'referred_by_code': agent.referred_by_code or '',
                        'plan_type': plan_type,
                    },
                )
            else:
                ref_code = request.session.get('ref_code') or request.session.get('championship_ref_id')
                if ref_code:
                    if str(ref_code).startswith('PA-'):
                        agent.referred_by_code = ref_code
                        agent.save()
                    else:
                        from apps.admin_panel.models.referral_code import ReferralCode
                        ref_obj = ReferralCode.objects.filter(code=ref_code, is_active=True).first()
                        if ref_obj:
                            agent.referred_by_code = ref_code
                            if ref_obj.distributor_id:
                                agent.distributor_id = ref_obj.distributor_id
                                # ── Event: DISTRIBUTION (via referral code) ────────────
                                RegistrationActivityLog.log(
                                    RegistrationActivityLog.EVENT_DISTRIBUTION,
                                    request=request,
                                    agent=agent,
                                    draft_id=draft.pk,
                                    extra_details={
                                        'distributor_id': ref_obj.distributor_id,
                                        'referred_by_code': ref_code,
                                        'plan_type': plan_type,
                                        'via_ref_code': True,
                                    },
                                )
                            agent.save()
            
            # Calculate subscription duration
            trial_days = int(trial_config.get('duration_days', 30))
            sub_expiry = timezone.now() + timezone.timedelta(days=365)
            if plan_type == 'free_trial':
                sub_expiry = timezone.now() + timezone.timedelta(days=trial_days)

            # Find or create a pending/failed subscription to prevent MultipleObjectsReturned
            subscription = AgentSubscription.objects.filter(
                agent=agent,
                payment_status__in=['pending', 'failed'],
            ).order_by('-created_at').first()
            if subscription:
                subscription.selected_plan = plan_name or plan_type
                subscription.promo_code = applied_promo_code or None
                subscription.registration_amount = total_amount
                subscription.razorpay_order_id = razorpay_order_id
                subscription.payment_status = 'pending'
                subscription.status = 'inactive'
                subscription.save()
            else:
                subscription = AgentSubscription.objects.create(
                    agent=agent,
                    selected_plan=plan_name or plan_type,
                    promo_code=applied_promo_code or None,
                    registration_amount=total_amount,
                    payment_status='pending',
                    status='inactive',
                    razorpay_order_id=razorpay_order_id
                )

            # ── Event: CLAIM_BUTTON ───────────────────────────────────────
            RegistrationActivityLog.log(
                RegistrationActivityLog.EVENT_CLAIM_BUTTON,
                request=request,
                agent=agent,
                draft_id=draft.pk,
                subscription_id=subscription.pk,
                extra_details={
                    'plan_type': plan_type,
                    'plan_name': plan_name,
                    'amount': str(total_amount),
                    'razorpay_order_id': razorpay_order_id or '',
                    'promo_code': applied_promo_code or '',
                    'is_mock': mock_checkout,
                },
            )

            # If 0 amount: complete instantly
            if amount_paise == 0:
                subscription.payment_status = 'completed'
                subscription.status = 'active'
                subscription.starts_at = timezone.now()
                subscription.expires_at = sub_expiry
                subscription.save()
                
                agent.status = 'active'
                if plan_type == 'free_trial':
                    agent.trial_ends_at = timezone.now() + timezone.timedelta(days=trial_days)
                    upgrade_discount = SiteSetting.get_value('trial_upgrade_discount', 20)
                    agent.upgrade_discount_percent = int(upgrade_discount)
                agent.save()

                # Best-effort side effects, each in its own savepoint.
                _isolated('Referral credit during free checkout', lambda: _credit_referral_conversion(agent))
                _isolated('Referral code generation', lambda: _ensure_referral_code(agent))

                queue_invoice_and_welcome(agent.id, subscription.id)

                instant_complete = True
    except Exception as db_err:
        logger.error(f"Database transaction error in agent_register_complete: {db_err}")
        return JsonResponse({
            'success': False,
            'message': 'Database error occurred. Please try again.'
        }, status=500)

    if instant_complete:
        from apps.distributors.views.dashboard import is_distributor
        try:
            user = create_or_link_django_user(agent)
            login_agent_user(request, user)
        except Exception as login_err:
            logger.error(f"Instant checkout login failed for agent {getattr(agent, 'id', None)}: {login_err}")

        request.session.pop('current_draft_id', None)
        request.session.pop('reg_step', None)
        request.session.pop('ref_code', None)
        request.session.pop('pending_checkout', None)
        request.session['auto_show_invite_studio'] = True

        return JsonResponse(_activation_success_payload(
            request,
            agent,
            message='Registration completed successfully! Welcome to PadosiAgent.',
        ))

    request.session['pending_checkout'] = {
        'agent_id': agent.id,
        'order_id': razorpay_order_id,
        'plan_type': plan_type,
        'plan_name': plan_name,
    }
    request.session.modified = True

    return JsonResponse(checkout_payload(
        razorpay_order_id,
        amount_paise,
        agent,
        is_mock=mock_checkout,
        request=request,
    ))


def _payer_signature_valid(order_id, payment_id, signature):
    """True when Razorpay's checkout signature proves the caller made this payment.

    The signature (HMAC of order_id|payment_id with our secret) is only handed
    to the browser that completed the payment, so it identifies the payer.
    """
    if not (order_id and payment_id and signature):
        return False
    if is_mock_payment(order_id, signature):
        return False
    try:
        client = razorpay_client()
        if client is None:
            return False
        client.utility.verify_payment_signature({
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature,
        })
        return True
    except Exception:
        return False


class _PaymentAlreadyFinalized(Exception):
    """Raised inside the activation transaction when the order is already paid."""

    def __init__(self, agent):
        super().__init__('payment already finalized')
        self.agent = agent


def _finalize_razorpay_payment(request, data):
    """
    Verify Razorpay payment signature and activate registration.
    Used by verify-payment (JSON) and payment-callback (redirect).
    """
    pending = request.session.get('pending_checkout') or {}
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id') or pending.get('order_id')
    razorpay_signature = data.get('razorpay_signature')
    # The agent and plan come from server state (checkout session / the priced
    # order), never from the request body: a client plan_type let an agent pay
    # the Starter price and be activated on Professional/Exclusive.
    agent_id = pending.get('agent_id')
    plan_name = pending.get('plan_name')
    plan_type = resolve_checkout_plan_slug(pending.get('plan_type'), plan_name)

    from apps.agents.models import Agent, AgentSubscription, Invoice
    from apps.home.models import SiteSetting
    from apps.admin_panel.models.referral_code import ReferralCode
    from apps.admin_panel.models.referral_usage import ReferralUsage

    if razorpay_order_id:
        existing_sub = AgentSubscription.objects.filter(
            razorpay_order_id=razorpay_order_id,
            payment_status='completed'
        ).first()
        existing_invoice = Invoice.objects.filter(
            razorpay_order_id=razorpay_order_id,
            payment_status='paid',
        ).first()

        if existing_sub or existing_invoice:
            agent_obj = existing_sub.agent if existing_sub else existing_invoice.agent
            from apps.agents.services.account_auth import agent_can_access_dashboard
            if not agent_can_access_dashboard(agent_obj):
                return {
                    'success': False,
                    'message': 'Payment is not completed yet.',
                }
            # A known order id alone must never sign the caller in as the order's
            # agent, nor re-sync their plan/subscriptions (replaying an old order
            # id downgraded agents). The payer is recognised either by this
            # browser's checkout session or by a valid Razorpay signature for
            # this order (e.g. UPI app switch landed in a different browser).
            if not (
                _session_owns_agent(request, agent_obj)
                or _payer_signature_valid(razorpay_order_id, razorpay_payment_id, razorpay_signature)
            ):
                return {
                    'success': True,
                    'message': 'Payment already processed. Please log in to continue.',
                    'redirect_url': reverse('agents:agent_login'),
                }
            completed_sub = existing_sub
            if completed_sub and completed_sub.selected_plan:
                synced_slug = plan_slug_from_name(completed_sub.selected_plan)
                if synced_slug and synced_slug != agent_obj.plan_type:
                    agent_obj.plan_type = synced_slug
                    agent_obj.save(update_fields=['plan_type', 'updated_at'])
            if completed_sub:
                _deactivate_superseded_subscriptions(agent_obj, completed_sub.pk)
            try:
                user = create_or_link_django_user(agent_obj)
                login_agent_user(request, user)
            except Exception as login_err:
                logger.error(f"Idempotent payment login failed: {login_err}")

            request.session.pop('current_draft_id', None)
            request.session.pop('reg_step', None)
            request.session.pop('ref_code', None)
            request.session.pop('pending_checkout', None)

            return _activation_success_payload(
                request,
                agent_obj,
                message='Payment already processed successfully.',
            )

    mock_checkout = is_mock_payment(razorpay_order_id, razorpay_signature)
    if mock_checkout:
        logger.error('Rejecting mock payment verification for order=%s', razorpay_order_id)
        return {
            'success': False,
            'message': 'Payment was not completed. Please pay through Razorpay to continue.',
        }

    if not razorpay_signature:
        return {
            'success': False,
            'message': 'Payment signature is missing. Cannot verify transaction.',
        }

    subscription = None
    try:
        client = razorpay_client()
        if client is None:
            return {'success': False, 'message': gateway_failure_message()}

        client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        })

        payment_info = client.payment.fetch(razorpay_payment_id)
        payment_status = payment_info.get('status')
        paid_amount_paise = payment_info.get('amount')

        if payment_status not in ('captured', 'authorized'):
            logger.error(
                "Razorpay Payment %s status is %s — rejecting activation.",
                razorpay_payment_id,
                payment_status,
            )
            return {'success': False, 'message': 'Payment is not completed.'}

        subscription = AgentSubscription.objects.filter(razorpay_order_id=razorpay_order_id).first()
        if not subscription:
            logger.error(f"No subscription found matching Razorpay Order {razorpay_order_id}")
            return {'success': False, 'message': 'Invalid transaction ID.'}

        expected_amount_paise = _expected_amount_paise(subscription.registration_amount)
        if not _paise_amounts_match(paid_amount_paise, expected_amount_paise):
            logger.critical(
                f"POTENTIAL PRICE TAMPERING DETECTED! "
                f"Agent ID: {agent_id}, Paid: {paid_amount_paise} paise, Expected: {expected_amount_paise} paise. "
                f"Razorpay Payment ID: {razorpay_payment_id}"
            )
            return {'success': False, 'message': 'Payment validation failed: Amount mismatch.'}

    except Exception as e:
        logger.error("Razorpay Signature/Amount Verification Failed: %s", e)
        return {'success': False, 'message': gateway_failure_message()}

    from django.db import transaction

    try:
        with transaction.atomic():
            # Lock the order row so the webhook and this callback cannot both
            # activate it (double invoice / welcome email / promo count).
            subscription = AgentSubscription.objects.select_for_update().get(pk=subscription.pk)
            agent = subscription.agent
            if not agent:
                return {'success': False, 'message': 'Agent record not found.'}
            if agent_id and str(agent.pk) != str(agent_id):
                logger.critical(
                    'Razorpay order %s belongs to agent #%s but checkout session names agent #%s — rejecting.',
                    razorpay_order_id, agent.pk, agent_id,
                )
                return {'success': False, 'message': 'Invalid transaction ID.'}
            if subscription.payment_status == 'completed':
                raise _PaymentAlreadyFinalized(agent)

            # The paid order's own plan wins; the session plan is only a fallback
            # for legacy orders whose selected_plan name does not resolve.
            order_plan = plan_slug_from_name(subscription.selected_plan or '')
            if order_plan:
                plan_type = order_plan
            elif not plan_type:
                plan_type = plan_slug_from_name(plan_name)

            is_upgrade = _is_plan_upgrade_payment(agent, razorpay_order_id)

            if plan_type:
                known_slugs = ('starter', 'professional', 'free_trial', 'exclusive', 'basic')
                if plan_type not in known_slugs:
                    try:
                        from apps.agents.models import SubscriptionPlan as _SPReg
                        sp = _SPReg.objects.filter(slug=plan_type).first()
                        if not sp:
                            sp = _SPReg.objects.filter(name__iexact=plan_type).first()
                        if sp and sp.slug:
                            plan_type = sp.slug
                    except Exception:
                        pass

            trial_config = SiteSetting.get_value('trial_plan_config', {'duration_days': 30})
            trial_days = int(trial_config.get('duration_days', 30))

            sub_expiry = timezone.now() + timezone.timedelta(days=365)
            if plan_type == 'free_trial':
                agent.status = 'active'
                agent.trial_ends_at = timezone.now() + timezone.timedelta(days=trial_days)
                upgrade_discount = SiteSetting.get_value('trial_upgrade_discount', 20)
                agent.upgrade_discount_percent = int(upgrade_discount)
                sub_expiry = timezone.now() + timezone.timedelta(days=trial_days)
            elif is_upgrade:
                if agent.status in ('pending_payment', 'incomplete', 'pending_accounts_payment'):
                    agent.status = 'pending_approval'
            else:
                agent.status = 'pending_approval'

            if plan_type:
                agent.plan_type = plan_type
            agent.registration_step = 2
            agent.save()

            paid_sub = subscription

            paid_sub.payment_status = 'completed'
            paid_sub.status = 'active'
            paid_sub.razorpay_payment_id = razorpay_payment_id
            paid_sub.razorpay_signature = razorpay_signature
            paid_sub.starts_at = timezone.now()
            paid_sub.expires_at = sub_expiry
            paid_sub.save()
            subscription = paid_sub
            _deactivate_superseded_subscriptions(agent, paid_sub.pk)

            # Best-effort side effects, each isolated so a failure can never
            # roll back the payment activation above.
            _isolated('Promo usage increment', lambda: _increment_promo_usage(subscription.promo_code))
            _isolated('Referral credit during payment success', lambda: _credit_referral_conversion(agent))
            _isolated('Championship qualification hook', lambda: _championship_qualification(agent, subscription))
            _isolated('Referral code generation', lambda: _ensure_referral_code(agent))

            # ── Event: PAYMENT_BUTTON ──────────────────────────────────────
            RegistrationActivityLog.log(
                RegistrationActivityLog.EVENT_PAYMENT_BUTTON,
                request=request,
                agent=agent,
                subscription_id=subscription.pk,
                extra_details={
                    'plan_type': plan_type,
                    'plan_name': plan_name,
                    'razorpay_payment_id': razorpay_payment_id or '',
                    'razorpay_order_id': razorpay_order_id or '',
                    'promo_code': (subscription.promo_code or ''),
                },
            )

            queue_invoice_and_welcome(agent.id, subscription.id)

        # Signature was verified above for this order and `agent` is the order's
        # own agent, so this is the payer — sign them in (works across browsers).
        try:
            user = create_or_link_django_user(agent)
            login_agent_user(request, user)
        except Exception as login_err:
            logger.error(f"Payment success login failed for agent {getattr(agent, 'id', None)}: {login_err}")

        request.session.pop('current_draft_id', None)
        request.session.pop('reg_step', None)
        request.session.pop('ref_code', None)
        request.session.pop('pending_checkout', None)
        request.session['auto_show_invite_studio'] = True

        return _activation_success_payload(
            request,
            agent,
            message='Payment successful and account activated.',
        )
    except _PaymentAlreadyFinalized as done:
        # Webhook (or a parallel callback) won the lock and already activated.
        # The signature for this order was verified in this request.
        try:
            login_agent_user(request, create_or_link_django_user(done.agent))
        except Exception as login_err:
            logger.error(f"Idempotent payment login failed: {login_err}")
        request.session.pop('pending_checkout', None)
        return _activation_success_payload(
            request,
            done.agent,
            message='Payment already processed successfully.',
        )
    except Exception as e:
        logger.error(f"Error activating account in payment_success: {str(e)}")
        return {'success': False, 'message': 'Failed to activate agent account.', 'status': 500}


@require_POST
@csrf_protect
def payment_success(request):
    """
    Handle successful payment webhook/callback.
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    result = _finalize_razorpay_payment(request, data)
    status = result.pop('status', None) or (200 if result.get('success') else 400)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def payment_callback(request):
    """
    Razorpay redirect landing page for netbanking/UPI.
    Checkout handler often never runs after the bank redirect.
    """
    payload = _razorpay_callback_payload(request)
    logger.info(
        'Razorpay payment callback order=%s payment=%s has_signature=%s',
        payload.get('razorpay_order_id'),
        payload.get('razorpay_payment_id'),
        bool(payload.get('razorpay_signature')),
    )

    has_pending_checkout = bool(request.session.get('pending_checkout'))
    login_url = reverse('agents:agent_login')

    if payload.get('razorpay_payment_id') and payload.get('razorpay_order_id') and payload.get('razorpay_signature'):
        # Retries (waiting for the bank to confirm capture) only for a genuine
        # payer — a valid signature or this browser's own checkout. Anyone else
        # used to hold a worker for ~7s per request.
        genuine = has_pending_checkout or _payer_signature_valid(
            payload.get('razorpay_order_id'),
            payload.get('razorpay_payment_id'),
            payload.get('razorpay_signature'),
        )
        attempts = 3 if genuine else 1
        for attempt in range(attempts):
            result = _finalize_razorpay_payment(request, payload)
            if result.get('success'):
                if result.get('redirect_url') == login_url:
                    return redirect(login_url)
                return redirect('agents:payment_complete')
            if attempt < attempts - 1:
                time.sleep(1.5)

    recovered_url = _recover_pending_razorpay_checkout(request, payload, retry=has_pending_checkout)
    if recovered_url:
        return redirect(recovered_url)

    logger.warning('Razorpay callback could not complete order=%s', payload.get('razorpay_order_id'))
    return redirect('agents:chooseplan')


def payment_complete(request):
    """Brief success message after verified payment, then auto-redirect to dashboard."""
    if not request.user.is_authenticated:
        return redirect('agents:chooseplan')

    from apps.agents.services.account_auth import resolve_agent_for_user, agent_can_access_dashboard
    from apps.distributors.views.dashboard import is_distributor
    try:
        agent = resolve_agent_for_user(request.user)
    except Exception:
        agent = None

    if not agent or not agent_can_access_dashboard(agent):
        return redirect('agents:chooseplan')

    redirect_url = reverse('distributors:agents_index') if is_distributor(request.user) else reverse('agents:agent_dashboard')
    return render(request, 'agents/payment_complete.html', {
        'agent_name': (getattr(agent, 'fullname', '') or '').strip(),
        'redirect_url': redirect_url,
        'hide_chatbot': True,
    })


@require_POST
@csrf_protect
def agent_verify_promo(request):
    """
    Verify promo code.
    Mirrors Laravel's AgentRegistrationController::verifyPromo.
    """
    try:
        data = json.loads(request.body)
        promo_code = data.get('promo_code', '').strip().upper()
    except (json.JSONDecodeError, AttributeError):
        promo_code = request.POST.get('promo_code', '').strip().upper()

    if not promo_code:
        return JsonResponse({'success': False, 'message': 'Promo code is required.'})

    try:
        promo = PromoCode.objects.filter(code__iexact=promo_code).first()
        if promo and promo.is_valid():
            request.session['applied_promo_code'] = promo.code
            request.session.modified = True
            return JsonResponse({
                'success': True,
                'message': f'Promo code "{promo.code}" is valid and will be applied at checkout!',
            })
        elif promo:
            return JsonResponse({
                'success': False,
                'message': 'Promo code has expired or is no longer valid.',
            })
    except Exception as e:
        logger.error(f"Promo verification error: {e}")

    return JsonResponse({
        'success': False,
        'message': 'Invalid or expired promo code.',
    })


@require_POST
@csrf_protect
def agent_clear_promo(request):
    """
    Clear the applied promo code from the session.
    Called when the user clicks 'Remove' on the plans page promo widget.
    """
    request.session.pop('applied_promo_code', None)
    request.session.modified = True
    return JsonResponse({'success': True, 'message': 'Promo code removed.'})


def referral_join(request, ref_code):
    """
    Referral link landing - captures ref code in session, increments clicks, and redirects to registration.
    Ported from Laravel route /join/{refCode}.
    Supports both legacy Free Trial ReferralCode and National Championship codes (PA-XXXXXX).
    """
    code_val = str(ref_code).strip().upper()

    # If code is for Referral Championship (PA-XXXXXX)
    if code_val.startswith('PA-'):
        from apps.referral_championship.models import ChampionshipParticipant
        if ChampionshipParticipant.objects.filter(referral_id=code_val).exists():
            return redirect('championship:public_landing', ref_id=code_val)

    # If code is for a SubDistributor
    from apps.distributors.models import SubDistributor
    sub_dist = SubDistributor.objects.filter(code=code_val, status='active').first()
    if sub_dist:
        sub_dist.clicks = (sub_dist.clicks or 0) + 1
        sub_dist.save(update_fields=['clicks'])
        request.session['ref_code'] = sub_dist.code
        request.session['sub_distributor_id'] = sub_dist.id
        request.session['distributor_id'] = sub_dist.distributor_id
        request.session['distributor_led_registration'] = True
        url = reverse('agents:agent_registration') + f"?ref={code_val}&show_trial=1"
        return redirect(url)

    from apps.admin_panel.models.referral_code import ReferralCode
    code = ReferralCode.objects.filter(code=code_val, is_active=True).first()
    if code:
        code.clicks = (code.clicks or 0) + 1
        code.save()
        request.session['ref_code'] = code.code
        if code.distributor_id:
            request.session['distributor_id'] = code.distributor_id
            request.session['distributor_led_registration'] = True
    
    # Redirect to registration page with query params
    url = reverse('agents:agent_registration') + f"?ref={code_val}&show_trial=1"
    return redirect(url)


def _email_belongs_to_portal_account(email):
    """True when an email is (or will be) a non-client portal identity.

    resolve_agent_for_user() links an agent to ANY auth_user with the same
    email, so a passwordless client account must never be created or signed in
    for an agent / insurance / distributor / staff email.
    """
    from django.contrib.auth.models import User
    from apps.agents.models import Agent

    if not email:
        return False
    if Agent.objects.filter(email__iexact=email).exists():
        return True
    return any(_is_portal_user(u) for u in User.objects.filter(email__iexact=email))


def _is_portal_user(user):
    """Staff, agent, insurance or distributor users — never passwordless-login targets."""
    from apps.agents.models import Agent

    if not user:
        return False
    if user.is_staff or user.is_superuser:
        return True
    if Agent.objects.filter(user=user).exists():
        return True
    if user.email and Agent.objects.filter(email__iexact=user.email).exists():
        return True
    if hasattr(user, 'insurance_profile'):
        return True
    if getattr(user, 'role', None) == 'distributor' or user.groups.filter(name='distributor').exists():
        return True
    return False


def _safe_local_redirect(request, url, default='/find-agents/'):
    from django.utils.http import url_has_allowed_host_and_scheme
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return url
    return default


@require_POST
@csrf_protect
def client_quick_register(request):
    """
    Client quick registration view. Replicates Laravel's ClientRegistrationController.quickRegister().
    Validates input, logins existing client, or creates a new client and user account.

    Sign-in here is passwordless, so it is only ever done for plain client
    accounts. Agent / insurance / distributor / staff accounts get the guest
    lead session only — never a login (this was an account takeover).
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        data = request.POST

    fullname = (data.get('fullname') or '').strip()
    email = (data.get('email') or '').strip().lower()
    mobile = (data.get('mobile') or '').strip()
    pincode = (data.get('pincode') or '').strip() or None

    # Validation
    errors = {}
    if not fullname:
        errors['fullname'] = ['Full name is required.']
    elif len(fullname) < 2 or len(fullname) > 100:
        errors['fullname'] = ['Name must be between 2 and 100 characters.']
    elif not re.match(r'^[\w\s.\-\']+$', fullname):
        errors['fullname'] = ['Name may only contain letters, spaces, dots, hyphens or apostrophes.']

    if not email:
        errors['email'] = ['Email is required.']
    elif '@' not in email:
        errors['email'] = ['Please enter a valid email address.']

    if not mobile:
        errors['mobile'] = ['Mobile number is required.']
    elif len(mobile) != 10 or not mobile.isdigit():
        errors['mobile'] = ['Mobile number must be exactly 10 digits.']
    elif not re.match(r'^[6-9][0-9]{9}$', mobile):
        errors['mobile'] = ['Please enter a valid Indian mobile number (starts with 6-9).']

    if pincode and (len(pincode) != 6 or not pincode.isdigit()):
        errors['pincode'] = ['Pincode must be exactly 6 digits.']

    if errors:
        return JsonResponse({
            'success': False,
            'message': 'Please fix the validation errors below.',
            'errors': errors
        }, status=422)

    from django.contrib.auth.models import User
    from apps.agents.models import Client, Agent
    from apps.agents.services.account_auth import DJANGO_AUTH_BACKEND
    
    existing_user = User.objects.filter(email=email).first()
    if not existing_user and mobile:
        existing_client = Client.objects.filter(mobile=mobile).select_related('user').first()
        if existing_client and existing_client.user:
            existing_user = existing_client.user
        else:
            existing_agent = Agent.objects.filter(mobile=mobile).select_related('user').first()
            if existing_agent and existing_agent.user:
                existing_user = existing_agent.user
    
    # A logged-in agent (or distributor) must not be converted into a client or
    # have their portal session hijacked when they use the client quick-register.
    current_is_logged_in_agent = (
        request.user.is_authenticated
        and Agent.objects.filter(user=request.user).exists()
    )

    redirect_to = _safe_local_redirect(request, data.get('redirect_url'))

    if existing_user and _is_portal_user(existing_user):
        # Privileged identity: keep the lead-capture session data the visitor
        # typed, but never mutate or sign in the portal account.
        request.session['quick_lead_user'] = {
            'fullname': fullname,
            'email': email,
            'mobile': mobile,
            'pincode': pincode,
        }
        request.session.modified = True
        return JsonResponse({
            'success': True,
            'status': 'success',
            'message': 'Welcome back! Redirecting...',
            'redirect': redirect_to,
        })

    if existing_user:
        # Plain client account (passwordless guest identity by design).
        is_client = Client.objects.filter(user=existing_user).exists()
        if not is_client:
            Client.objects.create(
                user=existing_user,
                mobile=mobile,
                pincode=pincode
            )

        request.session['quick_lead_user'] = {
            'fullname': fullname or getattr(existing_user, 'fullname', '') or existing_user.get_full_name() or existing_user.username,
            'email': existing_user.email or email,
            'mobile': mobile,
            'pincode': pincode,
        }
        from django.contrib.auth import login
        from apps.distributors.views.dashboard import is_distributor
        if not (request.user.is_authenticated and is_distributor(request.user)) and not current_is_logged_in_agent:
            login(request, existing_user, backend=DJANGO_AUTH_BACKEND)
        request.session.modified = True

        return JsonResponse({
            'success': True,
            'status': 'success',
            'message': 'Welcome back! Redirecting...',
            'redirect': redirect_to,
        })

    if _email_belongs_to_portal_account(email):
        # e.g. an agent that has no auth_user yet: creating one with this email
        # would let the visitor inherit that agent on next request.
        request.session['quick_lead_user'] = {
            'fullname': fullname,
            'email': email,
            'mobile': mobile,
            'pincode': pincode,
        }
        request.session.modified = True
        return JsonResponse({
            'success': True,
            'status': 'success',
            'message': 'Welcome back! Redirecting...',
            'redirect': redirect_to,
        })

    # Create new client account
    from django.db import transaction
    try:
        with transaction.atomic():
            # Create standard User
            username = email.split('@')[0]
            counter = 1
            base_username = username
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            # No password: client sign-in is passwordless, and password=email
            # was guessable by anyone who knew the address.
            user = User.objects.create_user(
                username=username,
                email=email,
                password=None,
                first_name=fullname.split(' ')[0],
                last_name=' '.join(fullname.split(' ')[1:])
            )

            # Create Client record
            Client.objects.create(
                user=user,
                mobile=mobile,
                pincode=pincode
            )

        # Log user in
        from django.contrib.auth import login
        from apps.distributors.views.dashboard import is_distributor
        if not (request.user.is_authenticated and is_distributor(request.user)) and not current_is_logged_in_agent:
            login(request, user, backend=DJANGO_AUTH_BACKEND)

        request.session['quick_lead_user'] = {
            'fullname': fullname,
            'email': email,
            'mobile': mobile,
            'pincode': pincode,
        }
        request.session.modified = True

        return JsonResponse({
            'success': True,
            'status': 'success',
            'message': 'Registration successful! Redirecting...',
            'redirect': redirect_to,
        })

    except Exception as e:
        logger.error(f"Client quick registration failed: {e}")
        return JsonResponse({
            'success': False,
            'status': 'error',
            'message': 'Unable to complete registration right now. Please try again.'
        }, status=500)


@require_POST
@csrf_protect
def payment_failure(request):
    """
    Handle failed payment notification.
    """
    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = request.POST

        pending = request.session.get('pending_checkout') or {}
        # Only act on the checkout this session started; a client-supplied
        # agent_id/order_id let any caller flip other agents' status/orders.
        agent_id = pending.get('agent_id')
        order_id = pending.get('order_id') or data.get('razorpay_order_id')
        from apps.agents.models import Agent, AgentSubscription

        agent = Agent.objects.filter(pk=agent_id).first() if agent_id else None
        subscription = None
        if order_id:
            subscription = AgentSubscription.objects.filter(razorpay_order_id=order_id).first()
            if subscription and not agent:
                agent = subscription.agent
        if agent and not _session_owns_agent(request, agent):
            return JsonResponse({'success': False, 'message': 'Checkout session not found.'}, status=403)
        if subscription and agent and subscription.agent_id != agent.pk:
            subscription = None
        if not subscription and agent:
            subscription = AgentSubscription.objects.filter(
                agent=agent,
                payment_status='pending'
            ).order_by('-created_at').first()

        if subscription:
            # Netbanking/UPI often fire a client "failed" event while the bank
            # payment is still in progress. Never mark failed in that case.
            error = data.get('error') if isinstance(data.get('error'), dict) else {}
            if _is_in_progress_razorpay_error(error):
                logger.info(
                    'Ignoring in-progress Razorpay failure for order %s step=%s',
                    order_id, error.get('step'),
                )
                return JsonResponse({
                    'success': True,
                    'ignored': True,
                    'message': 'Payment still in progress.',
                })

            agent = agent or subscription.agent
            if agent and verify_and_activate_pending_payment(agent):
                from apps.agents.services.account_auth import agent_can_access_dashboard
                agent.refresh_from_db()
                if agent_can_access_dashboard(agent):
                    return JsonResponse({
                        'success': True,
                        'already_completed': True,
                        'message': 'Payment already captured.',
                        'redirect_url': reverse('agents:agent_dashboard'),
                    })

            if subscription.payment_status != 'completed':
                subscription.payment_status = 'failed'
                subscription.save(update_fields=['payment_status'])
                logger.info(
                    'Razorpay client failure recorded for order %s; subscription marked failed',
                    order_id or subscription.razorpay_order_id,
                )

        # Only registration-stage agents move back to pending_payment; never
        # un-suspend / un-blacklist an account via a payment failure event.
        if agent and agent.status in ('incomplete', 'pending_payment', 'pending_accounts_payment', 'inactive'):
            agent.status = 'pending_payment'
            agent.save(update_fields=['status'])

        request.session.pop('pending_checkout', None)

        return JsonResponse({
            'success': True,
            'message': 'Payment failure logged.',
            'redirect_url': reverse('agents:chooseplan')
        })
    except Exception as e:
        logger.error(f"PAYMENT FAILURE LOG ERR: {e}")
        return JsonResponse({'success': False}, status=500)


from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """
    Asynchronous webhook handler to process Razorpay payment events.
    Verifies signature and activates the agent subscription.
    """
    payload = request.body
    received_signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE') or request.headers.get('X-Razorpay-Signature')
    webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')

    if not webhook_secret:
        logger.error("[Razorpay Webhook] RAZORPAY_WEBHOOK_SECRET is not configured.")
        return HttpResponse('Webhook secret not configured', status=400)

    # Verify signature
    if received_signature == 'test_signature_skip_verification' and settings.DEBUG:
        logger.info("[Razorpay Webhook] Skipping signature verification for local test simulation.")
    else:
        try:
            client = razorpay_client()
            if client is None:
                logger.error("[Razorpay Webhook] Razorpay keys not configured.")
                return HttpResponse('Unable to process webhook.', status=400)
            # verify_webhook_signature takes payload string, signature, secret
            client.utility.verify_webhook_signature(
                payload.decode('utf-8') if isinstance(payload, bytes) else payload,
                received_signature,
                webhook_secret
            )
        except Exception as sig_err:
            logger.error(f"[Razorpay Webhook] Signature verification failed: {sig_err}")
            return HttpResponse('Invalid signature', status=400)

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return HttpResponse('Invalid JSON payload', status=400)

    event = data.get('event')
    if not event:
        return HttpResponse('Invalid event', status=400)

    if event == 'payment.captured':
        payment = data['payload']['payment']['entity']
        order_id = payment.get('order_id')
        payment_id = payment.get('id')
        signature = received_signature

        from apps.agents.models import Agent, AgentSubscription, PromoCode, Invoice
        from apps.home.models import SiteSetting
        from django.utils import timezone

        subscription = AgentSubscription.objects.filter(razorpay_order_id=order_id).first()
        existing_invoice = Invoice.objects.filter(razorpay_order_id=order_id).first()
        
        if (subscription and subscription.payment_status == 'completed') or existing_invoice:
            return HttpResponse('Webhook processed successfully (already completed)', status=200)

        if subscription:
            agent = subscription.agent
            
            # Avoid duplicate activation
            if subscription.payment_status == 'completed':
                return HttpResponse('Webhook processed successfully (already completed)', status=200)

            # Verify amount paid matches subscription amount to prevent tampering
            paid_amount_paise = payment.get('amount')
            expected_amount_paise = _expected_amount_paise(subscription.registration_amount)
            if not _paise_amounts_match(paid_amount_paise, expected_amount_paise):
                logger.critical(
                    f"[Webhook] PRICE TAMPERING DETECTED! "
                    f"Order: {order_id}, Paid: {paid_amount_paise} paise, Expected: {expected_amount_paise} paise."
                )
                return HttpResponse('Payment validation failed: Amount mismatch.', status=400)

            from django.db import transaction
            try:
                with transaction.atomic():
                    subscription = AgentSubscription.objects.select_for_update().get(pk=subscription.pk)
                    if subscription.payment_status == 'completed':
                        # The browser callback activated it while we waited on the lock.
                        return HttpResponse('Webhook processed successfully (already completed)', status=200)
                    agent = subscription.agent
                    plan_type = _order_plan_slug(subscription, agent)
                    is_trial = plan_type == 'free_trial'

                    trial_config = SiteSetting.get_value('trial_plan_config', {'duration_days': 30})
                    trial_days = int(trial_config.get('duration_days', 30))
                    sub_expiry = timezone.now() + timezone.timedelta(days=365)
                    if is_trial:
                        sub_expiry = timezone.now() + timezone.timedelta(days=trial_days)

                    # Update subscription status
                    subscription.payment_status = 'completed'
                    subscription.status = 'active'
                    subscription.razorpay_payment_id = payment_id
                    subscription.razorpay_signature = signature
                    subscription.starts_at = timezone.now()
                    subscription.expires_at = sub_expiry
                    subscription.save()

                    # Update Agent status
                    agent.registration_step = 2
                    if is_trial:
                        agent.status = 'active'
                        agent.plan_type = 'free_trial'
                        agent.trial_ends_at = timezone.now() + timezone.timedelta(days=trial_days)
                        upgrade_discount = SiteSetting.get_value('trial_upgrade_discount', 20)
                        agent.upgrade_discount_percent = int(upgrade_discount)
                    else:
                        agent.status = 'pending_approval'
                        agent.plan_type = plan_type
                    agent.save()

                    # Best-effort side effects, each in its own savepoint.
                    _isolated('[Webhook] Referral credit processing', lambda: _credit_referral_conversion(agent))
                    _isolated('[Webhook] Referral code generation', lambda: _ensure_referral_code(agent))
                    _isolated('[Webhook] Promo usage increment',
                              lambda: _increment_promo_usage(subscription.promo_code))

                    # Link django user
                    user = create_or_link_django_user(agent)

                    queue_invoice_and_welcome(agent.id, subscription.id)

            except Exception as db_err:
                logger.error(f"[Webhook] Database transaction failed: {db_err}")
                return HttpResponse('Database transaction failed', status=500)

    elif event == 'refund.processed':
        return _handle_refund_webhook(data)

    return HttpResponse('Webhook processed successfully', status=200)


def _handle_refund_webhook(data):
    """Revoke a paid subscription once Razorpay confirms a FULL refund.

    Before this, refunds left the subscription 'completed', so the agent kept
    dashboard access and championship credit. Partial refunds are ignored.
    """
    from django.db import transaction
    from apps.agents.models import AgentSubscription, Invoice
    from apps.agents.services.account_auth import agent_has_completed_payment

    payload = data.get('payload') or {}
    payment = (payload.get('payment') or {}).get('entity') or {}
    payment_id = payment.get('id') or ((payload.get('refund') or {}).get('entity') or {}).get('payment_id')
    order_id = payment.get('order_id')
    try:
        amount = int(payment.get('amount') or 0)
        refunded = int(payment.get('amount_refunded') or 0)
    except (TypeError, ValueError):
        amount, refunded = 0, 0
    is_full_refund = payment.get('refund_status') == 'full' or (amount > 0 and refunded >= amount)
    if not payment_id or not is_full_refund:
        return HttpResponse('Refund noted (partial or unmatched)', status=200)

    from django.db.models import Q
    match = Q(razorpay_payment_id=payment_id)
    if order_id:
        match |= Q(razorpay_order_id=order_id)

    agents = {}
    try:
        with transaction.atomic():
            subs = list(AgentSubscription.objects.select_for_update().filter(match))
            if not subs:
                return HttpResponse('Refund noted (no matching subscription)', status=200)

            for sub in subs:
                if sub.payment_status == 'refunded':
                    continue
                sub.payment_status = 'refunded'
                sub.status = 'inactive'
                sub.save(update_fields=['payment_status', 'status', 'updated_at'])
                if sub.agent_id:
                    agents[sub.agent_id] = sub.agent

            Invoice.objects.filter(match, payment_status='paid').update(payment_status='refunded')

            for agent in agents.values():
                # Only drop access if no OTHER real payment remains (e.g. upgrades).
                if not agent_has_completed_payment(agent) and agent.status in ('active', 'pending_approval'):
                    agent.status = 'pending_payment'
                    agent.save(update_fields=['status'])
    except Exception as err:
        logger.error('[Webhook] Refund processing failed for payment %s: %s', payment_id, err)
        return HttpResponse('Refund processing failed', status=500)

    for agent in agents.values():
        try:
            from apps.referral_championship.services.qualification_service import revert_championship_qualification
            revert_championship_qualification(agent, reason='refund')
        except Exception as champ_err:
            logger.warning('[Webhook] Championship refund revert failed for agent %s: %s', agent.pk, champ_err)

    logger.info('[Webhook] Full refund processed for payment %s (%d agent(s) updated)', payment_id, len(agents))
    return HttpResponse('Refund processed', status=200)


from django.contrib.auth.decorators import login_required

def agent_register_failed(request):
    """
    Render payment failed page.
    """
    from apps.agents.models import Agent
    # Session only: ?agent_id= exposed any agent's name/email/mobile.
    pending = request.session.get('pending_checkout') or {}
    agent_id = request.session.get('current_agent_id') or pending.get('agent_id')
    agent = Agent.objects.filter(id=agent_id).first() if agent_id else None

    return render(request, 'agents/failed.html', {'agent': agent})


def fb_ad_signup(request):
    """
    Dedicated landing page and signup flow for Facebook Ads.
    Mirrors client_quick_register but fixes the password=email security issue,
    adds a transaction guard for concurrent email signups, and blocks agent accounts.
    """
    if request.method == 'GET':
        return render(request, 'public/fb_ad_signup.html')
        
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        data = request.POST

    fullname = (data.get('fullname') or '').strip()
    email = (data.get('email') or '').strip().lower()
    mobile = (data.get('mobile') or '').strip()
    pincode = (data.get('pincode') or '').strip()

    # --- Validation ---
    errors = {}
    if not fullname:
        errors['fullname'] = ['Full name is required.']
    elif len(fullname) < 2 or len(fullname) > 100:
        errors['fullname'] = ['Name must be between 2 and 100 characters.']
    elif not re.match(r'^[\w\s.\-\']+$', fullname):
        errors['fullname'] = ['Name may only contain letters, spaces, dots, hyphens or apostrophes.']

    if not email:
        errors['email'] = ['Email is required.']
    elif '@' not in email:
        errors['email'] = ['Please enter a valid email address.']

    if not mobile:
        errors['mobile'] = ['Mobile number is required.']
    elif len(mobile) != 10 or not mobile.isdigit():
        errors['mobile'] = ['Mobile number must be exactly 10 digits.']
    elif not re.match(r'^[6-9][0-9]{9}$', mobile):
        errors['mobile'] = ['Please enter a valid Indian mobile number.']

    if not pincode:
        errors['pincode'] = ['Pincode is required.']
    elif len(pincode) != 6 or not pincode.isdigit():
        errors['pincode'] = ['Pincode must be exactly 6 digits.']

    if errors:
        return JsonResponse({
            'success': False,
            'message': 'Please fix the validation errors below.',
            'errors': errors
        }, status=422)

    from django.contrib.auth.models import User
    from apps.agents.models import Client, Agent
    from django.contrib.auth import login
    from django.db import transaction
    
    try:
        with transaction.atomic():
            # Guard against duplicates via select_for_update if existing, else create carefully
            existing_user = User.objects.select_for_update().filter(email=email).first()
            
            # Security Check: this passwordless consumer flow must never sign in
            # (or create a look-alike of) an agent/insurance/distributor/staff
            # account — only plain client accounts.
            if _is_portal_user(existing_user) or (
                not existing_user and _email_belongs_to_portal_account(email)
            ):
                return JsonResponse({
                    'success': False,
                    'status': 'error',
                    'message': 'This email is already registered with another PadosiAgent portal — please use that login page.'
                }, status=403)

            if existing_user:
                is_client = Client.objects.filter(user=existing_user).exists()
                if not is_client:
                    Client.objects.create(
                        user=existing_user,
                        mobile=mobile,
                        pincode=pincode
                    )
                user_to_login = existing_user
                message = 'Welcome back! Redirecting...'
            else:
                username = email.split('@')[0]
                counter = 1
                base_username = username
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1

                user_to_login = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=fullname.split(' ')[0],
                    last_name=' '.join(fullname.split(' ')[1:])
                )
                
                # MODIFICATION 1: Avoid setting password to email for security
                user_to_login.set_unusable_password()
                user_to_login.save()

                Client.objects.create(
                    user=user_to_login,
                    mobile=mobile,
                    pincode=pincode
                )
                message = 'Registration successful! Redirecting...'

    except Exception as e:
        logger.error(f"FB Ad quick registration failed: {e}")
        return JsonResponse({
            'success': False,
            'status': 'error',
            'message': 'Unable to complete registration right now. Please try again.'
        }, status=500)

    # Set session for agent_capture_lead compatibility
    request.session['quick_lead_user'] = {
        'fullname': fullname,
        'email': email,
        'mobile': mobile,
        'pincode': pincode,
    }
    
    login(request, user_to_login)
    
    return JsonResponse({
        'success': True,
        'status': 'success',
        'message': message,
        'redirect': f'/find-agents/?pincode={pincode}'
    })

