from django.db import models
from django.contrib.auth.models import User

@property
def user_fullname(self):
    return f"{self.first_name} {self.last_name}".strip() or self.username

User.add_to_class('fullname', user_fullname)
def format_indian_number(num):
    try:
        num = float(num)
    except (ValueError, TypeError):
        return '0'
    if num >= 10000000:
        val = num / 10000000
        return f"{int(val) if val.is_integer() else round(val, 2)} Cr"
    elif num >= 100000:
        val = num / 100000
        return f"{int(val) if val.is_integer() else round(val, 2)} L"
    # Format with commas
    return f"{int(num) if num.is_integer() else num:,}"


class InvestmentType(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'investment_types'
        ordering = ['name']

    def __str__(self):
        return self.name

def clean_investment_types(types):
    if not types:
        return []
    if isinstance(types, str):
        import json
        try:
            types = json.loads(types)
        except Exception:
            types = [types]
    if not isinstance(types, list):
        types = [types]
    normalized = []
    has_sip_stp_swp = False
    for t in types:
        if not t:
            continue
        t_lower = str(t).strip().lower()
        if t_lower in ['sip', 'stp', 'swp', 'sip/stp/swp']:
            if not has_sip_stp_swp:
                normalized.append('SIP/STP/SWP')
                has_sip_stp_swp = True
        elif t_lower == 'bonds':
            continue
        else:
            if t_lower == 'lumpsum':
                normalized.append('Lumpsum')
            elif t_lower == 'elss':
                normalized.append('ELSS')
            elif t_lower == 'pms':
                normalized.append('PMS')
            elif t_lower == 'nps':
                normalized.append('NPS')
            elif t_lower == 'aif':
                normalized.append('AIF')
            else:
                normalized.append(str(t).strip())
    return normalized


class AgentDraft(models.Model):
    """
    Stores in-progress agent registration data, keyed by Django session.
    Matches the Laravel flow where Agent record is created at Step 1
    and updated through Step 2 before payment.
    """
    session_key = models.CharField(max_length=40, db_index=True)

    # OTP / Email verification
    email = models.EmailField(max_length=254)
    email_verified = models.BooleanField(default=False)

    # Step 1 — Basic Information
    fullname = models.CharField(max_length=70, blank=True, default='')
    mobile = models.CharField(max_length=15, blank=True, default='')
    agent_pincode = models.CharField(max_length=6, blank=True, default='')
    state = models.CharField(max_length=100, blank=True, default='')
    experience_range = models.CharField(max_length=50, blank=True, default='')
    segments = models.JSONField(default=list, blank=True)  # e.g. ["health","life"]
    promo_code = models.CharField(max_length=30, blank=True, default='')
    insurance_companies = models.JSONField(default=list, blank=True)
    address = models.CharField(max_length=255, blank=True, default='')
    client_base = models.CharField(max_length=50, blank=True, default='')
    slug = models.CharField(max_length=255, blank=True, default='')
    whatsapp = models.CharField(max_length=20, blank=True, default='')
    claims_settled = models.IntegerField(default=0)
    claim_amount = models.CharField(max_length=20, blank=True, default='')

    # Step 2 — Profile Details / Professional Details
    photo = models.ImageField(upload_to='agent_photos/', null=True, blank=True)
    about = models.TextField(blank=True, default='')
    languages = models.JSONField(default=list, blank=True)  # e.g. ["Hindi","English"]
    certifications = models.CharField(max_length=200, blank=True, default='')

    # Step 2 Professional Details matching RegisterStep2Request
    license_number = models.CharField(max_length=255, blank=True, default='')
    license_valid_till = models.DateField(null=True, blank=True)
    arn_number = models.CharField(max_length=255, blank=True, default='')
    euin_number = models.CharField(max_length=255, blank=True, default='')
    investment_valid_till = models.DateField(null=True, blank=True)
    investment_types = models.JSONField(default=list, blank=True)
    pan_number = models.CharField(max_length=20, blank=True, default='')
    date_of_birth = models.DateField(null=True, blank=True)

    # Step 3 — Registration Mode
    life_insurance = models.IntegerField(null=True, blank=True)
    health_insurance = models.IntegerField(null=True, blank=True)
    general_insurance = models.IntegerField(null=True, blank=True)
    motor = models.IntegerField(null=True, blank=True)
    desired_services = models.JSONField(default=list, blank=True)
    software_services = models.JSONField(default=list, blank=True)
    software_name = models.CharField(max_length=255, blank=True, default='')

    # Registration tracking
    registration_step = models.PositiveSmallIntegerField(default=0)
    # 0 = OTP pending, 1 = Step1 completed, 2 = Step2 completed

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_drafts'
        ordering = ['-created_at']

    def __str__(self):
        return f"AgentDraft({self.email}, step={self.registration_step})"

    def save(self, *args, **kwargs):
        self.investment_types = clean_investment_types(self.investment_types)
        super().save(*args, **kwargs)

    @property
    def normalized_investment_types(self):
        return clean_investment_types(self.investment_types)


class PromoCode(models.Model):
    """
    Django representation of Laravel's promo_codes table.
    Set to managed = True because the table is managed by Laravel/migrations.
    """
    code = models.CharField(max_length=255, unique=True)
    discount_type = models.CharField(max_length=20, default='percentage')  # percentage, fixed
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    max_uses = models.IntegerField(null=True, blank=True)
    times_used = models.IntegerField(default=0)
    applicable_plan = models.CharField(max_length=50, null=True, blank=True)  # all, basic, professional
    expires_at = models.DateTimeField(null=True, blank=True)
    is_free_trial = models.BooleanField(default=False)
    trial_plan_name = models.CharField(max_length=255, null=True, blank=True)
    trial_duration_days = models.IntegerField(null=True, blank=True)
    trial_price_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'promo_codes'
        managed = True

    def __str__(self):
        return f"PromoCode({self.code}, active={self.is_active})"

    def is_valid(self, plan_type=None):
        from django.utils import timezone
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        if self.max_uses is not None and self.times_used >= self.max_uses:
            return False
        if plan_type is not None and self.applicable_plan is not None:
            if self.applicable_plan not in ('all', plan_type):
                return False
        return True

    def calculate_discount(self, amount):
        if self.discount_type == 'percentage':
            return (float(amount) * float(self.discount_value)) / 100
        return min(float(self.discount_value), float(amount))

    def is_free_trial_code(self):
        return bool(self.is_free_trial)


class Agent(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    fullname = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    google_id = models.CharField(max_length=255, blank=True, null=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    mobile = models.CharField(max_length=20)
    user_types = models.JSONField(default=list, blank=True)
    insurance_companies = models.JSONField(default=list, blank=True)
    onboarded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='onboarded_agents')
    experience_range = models.CharField(max_length=50, blank=True, default='')
    client_base = models.CharField(max_length=50, blank=True, default='')
    registration_step = models.IntegerField(default=1)
    status = models.CharField(max_length=50, default='incomplete')
    plan_type = models.CharField(max_length=50, blank=True, default='')
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    upgrade_discount_percent = models.IntegerField(default=0)
    referred_by_code = models.CharField(max_length=50, blank=True, default='')
    referral_reward_type = models.CharField(max_length=50, blank=True, default='')
    referral_reward_claimed = models.BooleanField(default=False)
    agent_pincode = models.CharField(max_length=6, blank=True, default='')
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    badge = models.CharField(max_length=255, blank=True, default='')
    admin_notes = models.TextField(blank=True, default='')
    event_id = models.IntegerField(null=True, blank=True)
    registration_draft = models.JSONField(null=True, blank=True)
    distributor_id = models.IntegerField(null=True, blank=True)
    insurance_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_approved = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    achievement_photo_limit = models.PositiveSmallIntegerField(null=True, blank=True)
    profession = models.CharField(max_length=255, null=True, blank=True, default='LIC Agent')

    serviceableCities = models.ManyToManyField('City', db_table='agent_serviceable_cities', blank=True, related_name='agents')

    is_blacklisted = models.BooleanField(default=False)
    blacklist_reason = models.TextField(blank=True, null=True)
    blacklisted_at = models.DateTimeField(blank=True, null=True)
    blacklist_source = models.CharField(max_length=50, blank=True, null=True)

    payment_method = models.CharField(max_length=100, blank=True, default='')
    payment_reference = models.CharField(max_length=255, blank=True, default='')
    payment_recorded_at = models.DateTimeField(null=True, blank=True)
    payment_recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_agent_payments')

    class Meta:
        db_table = 'agents'
        managed = True

    def __str__(self):
        return f"Agent({self.email}, status={self.status})"

    def isOnFreeTrial(self):
        from django.utils import timezone
        return self.plan_type == 'free_trial' and self.trial_ends_at and self.trial_ends_at > timezone.now()

    def get_primary_profile(self):
        try:
            return self.profile
        except (models.ObjectDoesNotExist, AttributeError):
            return None

    def isTrialExpired(self):
        from django.utils import timezone
        return self.plan_type == 'free_trial' and self.trial_ends_at and self.trial_ends_at <= timezone.now()

    @property
    def activeSubscription(self):
        from django.utils import timezone
        return (
            self.subscriptions.filter(status='active', expires_at__gt=timezone.now())
            .order_by('-starts_at', '-created_at', '-id')
            .first()
        )

    @property
    def average_rating(self):
        approved_reviews = self.reviews.filter(is_approved=True)
        if approved_reviews.exists():
            return approved_reviews.aggregate(models.Avg('rating'))['rating__avg'] or 0.0
        return 0.0

    @property
    def review_count(self):
        return self.reviews.filter(is_approved=True).count()

    @property
    def star_rating_list(self):
        import math
        rating = self.average_rating
        full_stars = int(math.floor(rating))
        has_half = (rating - full_stars) >= 0.5
        stars = []
        for i in range(5):
            if i < full_stars:
                stars.append('full')
            elif i == full_stars and has_half:
                stars.append('half')
            else:
                stars.append('empty')
        return stars


    @property
    def experience_years(self):
        import re
        range_val = self.experience_range or ''
        match = re.search(r'(\d+)', range_val)
        if match:
            return int(match.group(1))
        if hasattr(self, 'profile') and self.profile and self.profile.experience_years:
            return self.profile.experience_years
        return 0

    def get_match_percent(self, user_pincode='', user_city=''):
        # Experience score
        exp_years = self.experience_years
        exp_score = min(20.0, (exp_years / 15.0) * 20.0)

        # Policy score
        try:
            client_base = int(self.client_base or 0)
        except ValueError:
            client_base = 0
        policy_score = min(20.0, (client_base / 500.0) * 20.0)

        # Achievement score
        perf = getattr(self, 'performanceStats', None)
        claims_processed_val = perf.claims_processed if perf else 0
        try:
            claims_processed = float(claims_processed_val or 0)
        except (ValueError, TypeError):
            claims_processed = 0.0
        achievement_score = min(20.0, (claims_processed / 100.0) * 20.0)

        # Location score
        profile = getattr(self, 'profile', None)
        agent_pincode = self.agent_pincode or (profile.service_pincodes[0] if (profile and profile.service_pincodes) else '')
        agent_city = (profile.office_address or '') if profile else ''
        
        user_pincode = str(user_pincode).strip()
        user_city = str(user_city).strip().lower()
        agent_pincode = str(agent_pincode).strip()
        agent_city = str(agent_city).strip().lower()

        if user_pincode and agent_pincode and user_pincode == agent_pincode:
            location_score = 15.0
        elif agent_city and user_city and agent_city == user_city:
            location_score = 12.0
        else:
            location_score = 8.0

        # Badge score
        badge_score = 0.0
        if self.email_verified_at or self.status == 'active':
            badge_score += 5.0
        if self.status == 'active':
            badge_score += 5.0
        active_sub = self.activeSubscription
        plan_label = active_sub.selected_plan.lower() if active_sub else ''
        is_trusted = 'professional' in plan_label or 'pro' in plan_label
        if is_trusted:
            badge_score += 5.0

        # Rating score
        rating = self.average_rating
        rating_score = min(10.0, (rating / 5.0) * 10.0)

        raw_total = exp_score + policy_score + achievement_score + location_score + badge_score + rating_score
        
        smart_rank = getattr(self, 'padosi_smart_rank', None)
        if smart_rank is not None:
            match_percent = int(min(99.0, max(80.0, 80.0 + (smart_rank / 165.0) * 19.0)))
        else:
            match_percent = int(min(99.0, max(80.0, 80.0 + (raw_total / 100.0) * 19.0)))

        return match_percent

    @property
    def formatted_client_base(self):
        try:
            val = int(self.client_base or 0)
        except ValueError:
            val = 0
        return format_indian_number(val)

    @property
    def ordered_insurance_segments(self):
        segments = list(self.insuranceSegments.values_list('segment_type', flat=True))
        segments = [s.strip().lower() for s in segments if s and s.strip() != '-']
        segments = list(set(segments))
        priority = ['health', 'life', 'motor', 'sme']
        ordered = []
        for p in priority:
            if p in segments:
                ordered.append(p)
        for s in segments:
            if s not in ordered:
                ordered.append(s)
        return ordered

    @property
    def display_name(self):
        if hasattr(self, 'profile') and self.profile and self.profile.display_name:
            return self.profile.display_name
        return self.fullname

    def get_effective_pincode(self):
        import re
        pincode = str(self.agent_pincode or '').strip()
        if pincode and re.match(r'^[1-9]\d{5}$', pincode):
            return pincode
            
        profile = getattr(self, 'profile', None)
        if profile:
            service_pincodes = profile.service_pincodes
            if isinstance(service_pincodes, list) and service_pincodes:
                for pin in service_pincodes:
                    pin = str(pin or '').strip()
                    if re.match(r'^[1-9]\d{5}$', pin):
                        return pin
        return None

    def save_location(self, pincode, lat, lng):
        self.agent_pincode = pincode
        self.latitude = lat
        self.longitude = lng
        self.save(update_fields=['agent_pincode', 'latitude', 'longitude', 'updated_at'])
        return True

    @property
    def is_trusted(self):
        active_sub = self.activeSubscription
        plan_label = active_sub.selected_plan if active_sub else ""
        if not plan_label:
            return False
        return "professional" in plan_label.lower() or "pro" in plan_label.lower()

    @property
    def is_approved_by_admin(self):
        return self.status == "active"

    @property
    def is_verified_agent(self):
        return bool(self.email_verified_at) or self.status == "active"

    @property
    def agent_slug(self):
        if hasattr(self, 'profile') and self.profile and self.profile.slug:
            return self.profile.slug
        return str(self.id)

    @property
    def whatsapp_raw(self):
        if hasattr(self, 'profile') and self.profile and self.profile.whatsapp:
            return self.profile.whatsapp
        return self.mobile

    @property
    def has_distance(self):
        dist = getattr(self, 'distance', None)
        return dist is not None and 0 <= dist < 5000

    @property
    def formatted_distance(self):
        dist = getattr(self, 'distance', None)
        if dist is None:
            return ""
        if dist < 1:
            return "Nearby"
        if dist > 100:
            return "📡 Far Away"
        return f"{dist:.1f}km away"

    @property
    def calculated_match_percent(self):
        val = getattr(self, 'match_percent', None)
        if val is None:
            val = self.get_match_percent()
        return val

    @property
    def match_color_class(self):
        pct = self.calculated_match_percent
        if pct > 90:
            return 'rac-match--green'
        elif pct >= 51:
            return 'rac-match--amber'
        return 'rac-match--red'

    @property
    def agent_city_display(self):
        first_city = self.serviceableCities.first()
        if first_city:
            remain = self.serviceableCities.count() - 1
            return first_city.name + (f" +{remain} more" if remain > 0 else "")
        if hasattr(self, 'profile') and self.profile and self.profile.office_address:
            return self.profile.office_address
        return ""

    @property
    def badge_list(self):
        if not self.badge or self.badge.lower() == 'none':
            return []
        all_badges = [b.strip() for b in self.badge.split(',') if b.strip()]
        badge_map = {
            'verified': {'class': 'badge-verified-official', 'icon': 'fa-circle-check', 'label': 'Verified'},
            'irdai': {'class': 'badge-irdai-official', 'icon': 'fa-medal', 'label': 'Licensed'},
            'trusted': {'class': 'badge-trusted-official', 'icon': 'fa-award', 'label': 'Trusted'},
        }
        res = []
        for b in all_badges:
            key = b.lower()
            if key in badge_map:
                res.append(badge_map[key])
            else:
                res.append({'class': 'badge-verified-official', 'icon': 'fa-check-circle', 'label': b.capitalize()})
        return res

    @property
    def sorted_career_timelines(self):
        timelines = list(self.careerTimelines.all())
        month_map = {
            'january': 1, 'jan': 1,
            'february': 2, 'feb': 2,
            'march': 3, 'mar': 3,
            'april': 4, 'apr': 4,
            'may': 5,
            'june': 6, 'jun': 6,
            'july': 7, 'jul': 7,
            'august': 8, 'aug': 8,
            'september': 9, 'sep': 9,
            'october': 10, 'oct': 10,
            'november': 11, 'nov': 11,
            'december': 12, 'dec': 12
        }
        
        def sort_key(t):
            try:
                y = int(t.year) if t.year and str(t.year).isdigit() else 0
            except ValueError:
                y = 0
            
            m_str = (t.month or '').strip().lower()
            m = month_map.get(m_str, 0)
            
            return (y, m, getattr(t, 'id', 0))
            
        return sorted(timelines, key=sort_key, reverse=False)

    @property
    def certification_entries(self):
        return self.careerTimelines.filter(event_type__iexact='certification').order_by('-year')

    @property
    def achievement_entries(self):
        return self.careerTimelines.filter(event_type__in=['Achievement', 'Award', 'Milestone', 'achievement', 'award', 'milestone']).order_by('-year')






class AgentSubscription(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='subscriptions')
    selected_plan = models.CharField(max_length=255)
    promo_code = models.CharField(max_length=255, null=True, blank=True)
    registration_amount = models.DecimalField(max_digits=10, decimal_places=2)
    razorpay_order_id = models.CharField(max_length=255, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=255, null=True, blank=True)
    razorpay_signature = models.CharField(max_length=255, null=True, blank=True)
    payment_status = models.CharField(max_length=50, default='pending')  # pending, completed, failed
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=50, default='inactive')  # active, inactive, expired
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_subscriptions'
        managed = True

    @property
    def is_active(self):
        return self.status == 'active'

    @property
    def is_expired(self):
        from django.utils import timezone
        return self.expires_at is not None and self.expires_at < timezone.now()

    @property
    def is_professional(self):
        return 'professional' in (self.selected_plan or '').lower()

    def __str__(self):
        return f"Subscription({self.selected_plan}, status={self.status})"


class AgentProfile(models.Model):
    agent = models.OneToOneField(Agent, on_delete=models.CASCADE, related_name='profile')
    slug = models.CharField(max_length=255, unique=True, blank=True)
    profile_photo_path = models.CharField(max_length=255, blank=True, null=True)
    display_name = models.CharField(max_length=255, blank=True, null=True)
    whatsapp = models.CharField(max_length=20, blank=True, null=True)
    languages = models.CharField(max_length=255, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    pan_number = models.CharField(max_length=20, blank=True, default='')
    license_number = models.CharField(max_length=255, blank=True, default='')
    license_valid_till = models.DateField(null=True, blank=True)
    arn_number = models.CharField(max_length=255, blank=True, default='')
    euin_number = models.CharField(max_length=255, blank=True, default='')
    investment_valid_till = models.DateField(null=True, blank=True)
    investment_types = models.JSONField(default=list, blank=True)
    software_name = models.CharField(max_length=255, blank=True, default='')
    portfolio_breakdown = models.JSONField(null=True, blank=True)
    desired_services = models.JSONField(null=True, blank=True)
    agency_name = models.CharField(max_length=255, blank=True, null=True)
    office_address = models.CharField(max_length=255, blank=True, null=True)
    service_pincodes = models.JSONField(null=True, blank=True)
    experience_years = models.IntegerField(default=0)
    has_pos_license = models.BooleanField(default=False)
    website_url = models.CharField(max_length=255, blank=True, null=True)
    social_links = models.JSONField(null=True, blank=True)
    career_highlights = models.CharField(max_length=500, blank=True, null=True)

    # Google Business Profile OAuth tokens
    gbp_access_token      = models.TextField(blank=True, null=True)
    gbp_refresh_token     = models.TextField(blank=True, null=True)
    gbp_token_expires_at  = models.DateTimeField(null=True, blank=True)

    # Professional License Document uploads
    irdai_license_doc = models.FileField(upload_to='app/public/insurance/', null=True, blank=True)
    amfi_license_doc  = models.FileField(upload_to='app/public/investment/', null=True, blank=True)

    is_profile_visible = models.BooleanField(default=True)
    show_certificates = models.BooleanField(default=True)
    show_achievements = models.BooleanField(default=True)
    show_reviews = models.BooleanField(default=True)
    is_card_visible = models.BooleanField(default=True)

    # Extended Profile Section Visibility Controls
    show_experience = models.BooleanField(default=True)
    show_claims_stats = models.BooleanField(default=True)
    show_client_base = models.BooleanField(default=True)
    show_ratings = models.BooleanField(default=True)
    show_languages = models.BooleanField(default=True)
    show_gallery = models.BooleanField(default=True)
    show_contact_info = models.BooleanField(default=True)
    show_social_links = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_profiles'
        managed = True

    def __str__(self):
        return f"Profile({self.agent.email})"

    def save(self, *args, **kwargs):
        self.investment_types = clean_investment_types(self.investment_types)
        if not self.slug:
            name = self.display_name or (self.agent.fullname if self.agent else 'agent')
            from django.utils.text import slugify
            base_slug = slugify(name) or 'agent'
            slug = base_slug
            count = 1
            while self.__class__.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def normalized_investment_types(self):
        return clean_investment_types(self.investment_types)

    @property
    def profile_photo_url(self):
        path = (self.profile_photo_path or '').strip()
        if not path:
            return '/static/img/avatar-icon.jpg'
        if path.startswith(('http://', 'https://')):
            if any(k in path.lower() for k in ['ngrok', 'localhost', '127.0.0.1']):
                from urllib.parse import urlparse
                import os
                from django.conf import settings
                parsed = urlparse(path)
                rel_path = parsed.path.lstrip('/')
                if rel_path.startswith('static/'):
                    check_path = os.path.join(settings.BASE_DIR, rel_path)
                    if os.path.exists(check_path):
                        return f"/{rel_path}"
                elif rel_path.startswith('media/'):
                    check_path = os.path.join(settings.MEDIA_ROOT, rel_path[6:])
                    if os.path.exists(check_path):
                        return f"/{rel_path}"
                return '/static/img/avatar-icon.jpg'
            return path

        import os
        import shutil
        from django.conf import settings

        normalized_path = path.replace('\\', '/').lstrip('/')

        # ── 1. Direct match under MEDIA_ROOT ──────────────────────────────────
        if os.path.exists(os.path.join(settings.MEDIA_ROOT, normalized_path)):
            return f"/media/{normalized_path}"

        # ── 2. Strip known prefixes and check again ───────────────────────────
        for prefix in ['app/public/', 'public/storage/', 'public/', 'storage/']:
            if normalized_path.startswith(prefix):
                stripped = normalized_path[len(prefix):]
                for sub in ['', 'app/public/']:
                    candidate = os.path.join(settings.MEDIA_ROOT, sub, stripped)
                    if os.path.exists(candidate):
                        return f"/media/{sub}{stripped}"
                break

        # ── 3. agent/profiles/FILENAME → media/app/public/profile/FILENAME ───
        #       These files come from the Laravel storage and need remapping.
        filename = os.path.basename(normalized_path)
        target_dir = os.path.join(settings.MEDIA_ROOT, 'app', 'public', 'profile')
        target_path = os.path.join(target_dir, filename)

        # If already copied to the target dir, serve it
        if os.path.exists(target_path):
            return f"/media/app/public/profile/{filename}"

        # ── 4. Try to locate the source file in the Laravel storage tree ─────
        #       Walk up from MEDIA_ROOT to find the Laravel project root.
        base_dir = settings.BASE_DIR  # …/django/padosi_agent
        # Laravel root is two levels up: …/10_6
        laravel_root = os.path.abspath(os.path.join(base_dir, '..', '..'))

        source_candidates = [
            # agent/profiles/FILENAME from Laravel storage
            os.path.join(laravel_root, 'storage', 'app', 'public', normalized_path),
            os.path.join(laravel_root, 'storage', 'app', 'public', 'agent', 'profiles', filename),
            os.path.join(laravel_root, 'public', 'storage', normalized_path),
            os.path.join(laravel_root, 'public', 'storage', 'agent', 'profiles', filename),
        ]

        for src in source_candidates:
            if os.path.exists(src) and os.path.isfile(src):
                try:
                    os.makedirs(target_dir, exist_ok=True)
                    shutil.copy2(src, target_path)
                    return f"/media/app/public/profile/{filename}"
                except Exception:
                    pass

        # ── 5. Return the default avatar if the file is completely missing ───
        return '/static/img/avatar-icon.jpg'

    @property
    def service_pincode(self):
        if self.service_pincodes and isinstance(self.service_pincodes, list) and len(self.service_pincodes) > 0:
            return self.service_pincodes[0]
        return ""

    @service_pincode.setter
    def service_pincode(self, value):
        if value:
            self.service_pincodes = [value]
        else:
            self.service_pincodes = []

    @property
    def whatsapp_digits(self):
        import re
        val = self.whatsapp or (self.agent.mobile if self.agent else '') or ''
        return re.sub(r'[^0-9]', '', str(val))

    @property
    def formatted_languages(self):
        if not self.languages:
            return "English, Hindi"
        langs = [l.strip().capitalize() for l in self.languages.split(',') if l.strip()]
        return ", ".join(langs)




class City(models.Model):
    name = models.CharField(max_length=255)
    state = models.CharField(max_length=255, blank=True, null=True)
    slug = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'cities'
        managed = True


class AgentInsuranceSegment(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='insuranceSegments')
    segment_type = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_insurance_segments'
        managed = True


class AgentPerformanceStat(models.Model):
    agent = models.OneToOneField(Agent, on_delete=models.CASCADE, related_name='performanceStats')
    claims_processed = models.IntegerField(default=0)
    claims_settled = models.IntegerField(default=0)
    claims_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.0)
    success_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    response_time = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_performance_stats'
        managed = True

    @property
    def formatted_claims_processed(self):
        return format_indian_number(self.claims_processed)

    @property
    def formatted_claims_amount(self):
        return format_indian_number(self.claims_amount)



class AgentLead(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='leads')
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    customer_email = models.EmailField(blank=True, null=True)
    customer_mobile = models.CharField(max_length=20, blank=True, null=True)
    customer_pincode = models.CharField(max_length=10, blank=True, null=True)
    interaction_type = models.CharField(max_length=50, blank=True, null=True)
    lead_status = models.CharField(max_length=50, default='new')
    service_type = models.CharField(max_length=255, blank=True, null=True)
    insurance_type = models.CharField(max_length=255, blank=True, null=True)
    insurance_company = models.CharField(max_length=255, blank=True, null=True)
    enquiry_requirements = models.TextField(blank=True, null=True)
    source_page = models.CharField(max_length=255, blank=True, null=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_leads'
        managed = True


class AgentProfileView(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='profile_views')
    view_date = models.DateField()
    view_count = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_profile_views'
        managed = True


class AgentReview(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    reviewer_name = models.CharField(max_length=255, blank=True, null=True)
    reviewer_email = models.EmailField(blank=True, null=True)
    reviewer_mobile = models.CharField(max_length=20, blank=True, null=True)
    rating = models.IntegerField(default=5)
    review = models.TextField(blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_reviews'
        managed = True

    @property
    def author_display(self):
        if self.reviewer_name:
            return self.reviewer_name
        if self.user:
            return getattr(self.user, 'fullname', '') or self.user.get_full_name() or self.user.username
        return 'User'

class AgentBackup(models.Model):
    # This id corresponds to the old agent's ID when they are deleted.
    # It acts as the primary key here, but it's not auto-incrementing in the context of inserts 
    # from the trigger, although Django will make it a bigserial PK by default.
    user_id = models.IntegerField(null=True, blank=True)
    event_id = models.IntegerField(null=True, blank=True)
    distributor_id = models.IntegerField(null=True, blank=True)
    fullname = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    google_id = models.CharField(max_length=255, blank=True, null=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    mobile = models.CharField(max_length=20, null=True, blank=True)
    registration_step = models.IntegerField(null=True, blank=True)
    agent_pincode = models.CharField(max_length=6, blank=True, null=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    plan_type = models.CharField(max_length=50, blank=True, null=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    upgrade_discount_percent = models.IntegerField(null=True, blank=True)
    referred_by_code = models.CharField(max_length=50, blank=True, null=True)
    referral_reward_type = models.CharField(max_length=50, blank=True, null=True)
    referral_reward_claimed = models.BooleanField(default=False)
    status = models.CharField(max_length=50, blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    badge = models.CharField(max_length=255, blank=True, null=True)
    admin_notes = models.TextField(blank=True, null=True)
    registration_draft = models.JSONField(null=True, blank=True)
    user_types = models.JSONField(null=True, blank=True)
    insurance_companies = models.JSONField(null=True, blank=True)
    experience_range = models.CharField(max_length=50, blank=True, null=True)
    client_base = models.CharField(max_length=50, blank=True, null=True)
    achievement_photo_limit = models.PositiveSmallIntegerField(null=True, blank=True)
    profession = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'agent_backup'
        managed = True


    @property
    def star_display(self):
        return '⭐' * min(5, max(0, int(self.rating or 0)))

    @property
    def author_display(self):
        if self.reviewer_name:
            return self.reviewer_name
        if self.user:
            return getattr(self.user, 'fullname', '') or self.user.get_full_name() or self.user.username
        return 'User'


class AgentFamilyLicense(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='familyLicenses')
    full_name = models.CharField(max_length=255)
    relationship = models.CharField(max_length=255)
    license_number = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_family_licenses'
        managed = True


class AgentPortfolio(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='portfolios')
    segment_type = models.CharField(max_length=255)
    primary_companies = models.JSONField(null=True, blank=True)
    secondary_companies = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_portfolios'
        managed = True


def resolve_stored_file_url(path, fallback_subdirs=None, missing='/static/img/avatar-icon.jpg'):
    path = (path or '').strip()
    if not path:
        return missing
    if path.startswith(('http://', 'https://')):
        if any(k in path.lower() for k in ['ngrok', 'localhost', '127.0.0.1']):
            from urllib.parse import urlparse
            import os
            from django.conf import settings
            parsed = urlparse(path)
            rel_path = parsed.path.lstrip('/')
            if rel_path.startswith('static/'):
                check_path = os.path.join(settings.BASE_DIR, rel_path)
                if os.path.exists(check_path):
                    return f"/{rel_path}"
            elif rel_path.startswith('media/'):
                check_path = os.path.join(settings.MEDIA_ROOT, rel_path[6:])
                if os.path.exists(check_path):
                    return f"/{rel_path}"
            return missing
        return path

    import os
    from django.conf import settings

    normalized_path = path.replace('\\', '/').lstrip('/')

    # 1. Direct match under MEDIA_ROOT
    if os.path.exists(os.path.join(settings.MEDIA_ROOT, normalized_path)):
        return f"/media/{normalized_path}"

    subdirs = list(fallback_subdirs) if fallback_subdirs else []
    default_subdirs = [
        'app/public/achievement',
        'app/public/photo/achievements',
        'app/public/profile',
        'app/public/photo/profiles',
        'app/public/insurance',
        'app/public/investment',
        'app/public',
        'uploads/achievements',
        'agent/achievements',
        'agent/profiles',
    ]
    for s in default_subdirs:
        if s not in subdirs:
            subdirs.append(s)

    # 2. Strip known prefixes and test
    for prefix in ['app/public/', 'public/storage/', 'public/', 'storage/', 'agent/achievements/', 'agent/profiles/']:
        if normalized_path.startswith(prefix):
            stripped = normalized_path[len(prefix):]
            if os.path.exists(os.path.join(settings.MEDIA_ROOT, stripped)):
                return f"/media/{stripped}"
            if os.path.exists(os.path.join(settings.MEDIA_ROOT, 'app/public', stripped)):
                return f"/media/app/public/{stripped}"
            for subdir in subdirs:
                candidate = os.path.join(settings.MEDIA_ROOT, subdir, stripped)
                if os.path.exists(candidate):
                    return f"/media/{subdir}/{stripped}"

    # 3. Match by filename across fallback / candidate subdirs
    filename = os.path.basename(normalized_path)
    if filename:
        for subdir in subdirs:
            candidate = os.path.join(settings.MEDIA_ROOT, subdir, filename)
            if os.path.exists(candidate):
                return f"/media/{subdir}/{filename}"

    return f"/media/{normalized_path}"


class AgentAchievementPhoto(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='achievementPhotos')
    photo_path = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_achievement_photos'
        managed = True

    @property
    def photo_url(self):
        return resolve_stored_file_url(
            self.photo_path,
            fallback_subdirs=(
                'app/public/achievement',
                'app/public/photo/achievements',
                'uploads/achievements',
                'agent/achievements',
            ),
            missing='/static/img/avatar-icon.jpg',
        )


class AgentLeadPreference(models.Model):
    agent = models.OneToOneField(Agent, on_delete=models.CASCADE, related_name='leadPreferences')
    leads_new_business = models.BooleanField(default=True)
    leads_portfolio_analysis = models.BooleanField(default=True)
    portfolio_charging = models.CharField(max_length=50, blank=True, default='free')
    portfolio_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    leads_claims_support = models.BooleanField(default=True)
    claims_charging = models.CharField(max_length=50, blank=True, default='free')
    claims_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    claims_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_lead_preferences'
        managed = True


class AgentProductExpertise(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='productExpertise')
    segment_type = models.CharField(max_length=100)
    product_name = models.CharField(max_length=255)
    expertise_level = models.IntegerField(default=0)
    is_custom = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_product_expertise'
        managed = True


class AgentCareerTimeline(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='careerTimelines')
    event_type = models.CharField(max_length=255)
    event_text = models.TextField()
    month = models.CharField(max_length=50, blank=True, default='')
    year = models.CharField(max_length=4)
    # Stable key linking this row to an auto-detected suggestion.
    # Set when an entry is created via the "Auto-detected" suggestions panel.
    # NULL for all manually-created entries (existing rows unaffected).
    suggestion_key = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_career_timelines'
        managed = True


class AgentDeviceToken(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, db_column='agent_id', related_name='device_tokens')
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=50, null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'agent_device_tokens'
        managed = True

    def __str__(self):
        return f"DeviceToken({self.token[:20]}..., agent={self.agent_id})"


class Event(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    event_date = models.DateField()

    class Meta:
        db_table = 'events'
        managed = True

    def __str__(self):
        return self.name


class AgentProfileEditLog(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='edit_logs')
    edited_by = models.CharField(max_length=50)
    edited_by_id = models.IntegerField(null=True, blank=True)
    step = models.IntegerField(null=True, blank=True)
    step_label = models.CharField(max_length=255, null=True, blank=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    status_before = models.CharField(max_length=50, null=True, blank=True)
    status_after = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_profile_edit_logs'
        managed = True

    def __str__(self):
        return f"EditLog(agent={self.agent_id}, step={self.step})"


class BlockedIp(models.Model):
    ip_address = models.CharField(max_length=45, unique=True)
    reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'blocked_ips'
        managed = True

    def __str__(self):
        return f"BlockedIp({self.ip_address})"


class Client(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    mobile = models.CharField(max_length=15, null=True, blank=True)
    pincode = models.CharField(max_length=10, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'clients'
        managed = True

    def __str__(self):
        return f"Client({self.user.username})"


class Invoice(models.Model):
    invoice_number = models.CharField(max_length=255, unique=True)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='invoices')
    agent_name = models.CharField(max_length=255)
    agent_email = models.EmailField()
    agent_mobile = models.CharField(max_length=20, null=True, blank=True)
    agent_address = models.CharField(max_length=255, null=True, blank=True)
    agent_state = models.CharField(max_length=100, null=True, blank=True)
    plan_name = models.CharField(max_length=255)
    plan_type = models.CharField(max_length=50)
    base_amount = models.DecimalField(max_digits=10, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    discount_folder = models.CharField(max_length=255)
    promo_code = models.CharField(max_length=255, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=255, null=True, blank=True)
    razorpay_order_id = models.CharField(max_length=255, null=True, blank=True)
    payment_status = models.CharField(max_length=50, default='paid')
    pdf_path = models.CharField(max_length=255, null=True, blank=True)
    synced_to_sheet = models.BooleanField(default=False)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'invoices'
        managed = True

    def __str__(self):
        return f"Invoice({self.invoice_number}, total={self.total_amount})"

    @staticmethod
    def resolve_discount_folder(discount_percent, total_amount):
        if float(total_amount) <= 1.00:
            return '1re'
        discount_percent = float(discount_percent)
        if discount_percent == 0:  return 'no_discount'
        if discount_percent == 10: return '10_percent'
        if discount_percent == 25: return '25_percent'
        if discount_percent == 50: return '50_percent'
        return 'others'

    @staticmethod
    def folder_label(folder):
        labels = {
            'no_discount': 'No Discount',
            '10_percent': '10%',
            '25_percent': '25%',
            '50_percent': '50%',
            '1re': '₹1 (Special)',
        }
        return labels.get(folder, 'Others')


class AgentBioGenerationLog(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='bio_generation_logs', db_constraint=False)
    generated_at = models.DateTimeField(auto_now_add=True)
    prompt_version = models.CharField(max_length=50, default='v1.0')
    llm_model = models.CharField(max_length=100, default='llama-3.3-70b-versatile')
    generation_time = models.FloatField(null=True, blank=True)
    tokens_used = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=50, default='success')  # success, failure
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'agent_bio_generation_logs'
        ordering = ['-generated_at']


class AgentNotification(models.Model):
    """
    DB-backed in-app notification for agents.
    Mirrors Laravel's agent_notifications table (agent_id, title, body, is_read).
    managed=False: the table is owned by the Laravel schema (shared MySQL DB),
    exactly like the admin_panel mirror models.
    """
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, db_column='agent_id', related_name='notifications')
    title = models.CharField(max_length=191)
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'agent_notifications'
        managed = False
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification({self.title}, agent={self.agent_id}, read={self.is_read})"


class FavoriteAgent(models.Model):
    """
    Favorites: a logged-in user can favourite an agent profile.
    Mirrors Laravel's favorite_agents table (user_id, agent_id).
    user maps to Django auth.User — the port keeps auth_user.id == users.id
    for the same person (see admin_panel.views.insurance), so ids align with
    the Laravel-side user space.
    """
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, db_column='user_id', related_name='favorite_agents')
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, db_column='agent_id', related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'favorite_agents'
        managed = False
        ordering = ['-created_at']

    def __str__(self):
        return f"Favorite(user={self.user_id}, agent={self.agent_id})"


class EventRegistration(models.Model):
    """
    Public event registration funnel — mirrors Laravel's event_registrations table.
    Session-driven: current_step 1 = form, 2 = plan chosen, 3 = payment done.
    """
    event = models.ForeignKey(Event, on_delete=models.CASCADE, db_column='event_id', related_name='event_registrations')
    fullname = models.CharField(max_length=255)
    email = models.EmailField(max_length=255)
    mobile = models.CharField(max_length=255)
    insurance_segments = models.JSONField(default=list)
    pincode = models.CharField(max_length=255, null=True, blank=True)
    experience = models.CharField(max_length=255, null=True, blank=True)
    promocode = models.CharField(max_length=255, null=True, blank=True)
    current_step = models.PositiveSmallIntegerField(default=1)
    selected_plan = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=20, default='incomplete')  # incomplete, completed
    payment_status = models.CharField(max_length=255, default='pending')  # pending, success, failed
    razorpay_order_id = models.CharField(max_length=255, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'event_registrations'
        managed = False
        ordering = ['-created_at']

    def __str__(self):
        return f"EventRegistration({self.email}, {self.payment_status})"


class Participant(models.Model):
    """
    Event participant (Facebook auto-post / share flow).
    Mirrors Laravel's participants table (plus the Facebook connection columns
    the Laravel FacebookPostController writes to — added via migration 0014).
    """
    full_name = models.CharField(max_length=191)
    email = models.EmailField(max_length=191, unique=True)
    phone_number = models.CharField(max_length=191)
    have_insurance = models.CharField(max_length=5, null=True, blank=True)   # yes / no
    insurance_products = models.JSONField(null=True, blank=True)
    insurance_planning = models.CharField(max_length=191, null=True, blank=True)
    mutual_fund = models.CharField(max_length=5, null=True, blank=True)      # yes / no
    mf_plan = models.CharField(max_length=191, null=True, blank=True)
    thank_my_padosi = models.CharField(max_length=191, null=True, blank=True)
    thank_my_padosi_for = models.TextField(null=True, blank=True)
    participant_shared = models.CharField(max_length=5, default='No')        # Yes / No
    shareable_id = models.CharField(max_length=191, null=True, blank=True)
    registration_completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    # Facebook connection fields (used by the facebook API module)
    facebook_access_token = models.TextField(null=True, blank=True)
    facebook_user_id = models.CharField(max_length=191, null=True, blank=True)
    facebook_post_id = models.CharField(max_length=191, null=True, blank=True)
    facebook_post_url = models.CharField(max_length=500, null=True, blank=True)
    status = models.CharField(max_length=50, default='registered')
    manual_share = models.BooleanField(default=False)
    screenshot_path = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = 'participants'
        managed = False

    def __str__(self):
        return f"Participant({self.email}, shared={self.participant_shared})"

    def mark_as_shared(self):
        self.participant_shared = 'Yes'
        self.save(update_fields=['participant_shared', 'updated_at'])

    def is_shared(self):
        return self.participant_shared == 'Yes'


# Open Graph image cache invalidation signals
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

OG_IMAGE_CACHE_VERSION = 'v2'


def og_image_cache_key(agent_id):
    return f'og_image_agent_card_{OG_IMAGE_CACHE_VERSION}_{agent_id}'


@receiver(post_save, sender=AgentProfile)
@receiver(post_delete, sender=AgentProfile)
def clear_og_image_on_profile_change(sender, instance, **kwargs):
    if instance.agent_id:
        cache.delete(og_image_cache_key(instance.agent_id))

@receiver(post_save, sender=AgentPerformanceStat)
@receiver(post_delete, sender=AgentPerformanceStat)
def clear_og_image_on_performance_change(sender, instance, **kwargs):
    if instance.agent_id:
        cache.delete(og_image_cache_key(instance.agent_id))

@receiver(post_save, sender=AgentReview)
@receiver(post_delete, sender=AgentReview)
def clear_og_image_on_review_change(sender, instance, **kwargs):
    if instance.agent_id:
        cache.delete(og_image_cache_key(instance.agent_id))

@receiver(post_save, sender=Agent)
@receiver(post_delete, sender=Agent)
def clear_og_image_on_agent_change(sender, instance, **kwargs):
    cache.delete(og_image_cache_key(instance.id))


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=50, unique=True, null=True, blank=True)
    description = models.TextField(blank=True, default='')
    color_theme = models.CharField(max_length=50, default='starter-theme')
    badge_text = models.CharField(max_length=50, blank=True, null=True)
    sort_order = models.IntegerField(default=0)
    
    html_code = models.TextField(blank=True, default='')
    actual_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discounted_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Visibility toggles for agent features
    show_profile_section = models.BooleanField(default=True)
    show_agent_certificate = models.BooleanField(default=True)
    show_career_timeline = models.BooleanField(default=True)
    show_professional_bio = models.BooleanField(default=True)
    show_social_media = models.BooleanField(default=True)
    show_new_business_leads = models.BooleanField(default=True)
    show_portfolio = models.BooleanField(default=True)
    show_claim_support = models.BooleanField(default=True)
    show_companies = models.BooleanField(default=True)
    show_achievement = models.BooleanField(default=True)
    show_lead_status = models.BooleanField(default=True)
    show_sales_insights = models.BooleanField(default=True)
    show_recent_leads = models.BooleanField(default=True)
    
    # New Plan-Based Feature Access Control fields
    show_performance_stats = models.BooleanField(default=True)
    show_rank_boost_tips = models.BooleanField(default=True)
    show_view_public_profile_btn = models.BooleanField(default=True)
    show_edit_profile_full = models.BooleanField(default=True)
    show_edit_profile_basic = models.BooleanField(default=True)
    show_edit_profile_professional = models.BooleanField(default=True)
    show_edit_profile_portfolio = models.BooleanField(default=True)
    show_edit_profile_additional = models.BooleanField(default=True)
    show_review_management = models.BooleanField(default=True)
    is_listed_in_directory = models.BooleanField(default=True)
    premium_priority_support = models.BooleanField(default=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subscription_plans'
        managed = True
        
    def __str__(self):
        return self.name

class UserPlanProgress(models.Model):
    draft = models.ForeignKey(AgentDraft, on_delete=models.CASCADE, null=True, blank=True)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, null=True, blank=True, db_constraint=False)
    plan_key = models.CharField(max_length=50) # e.g., 'exclusive_gamified'
    discount_unlocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_plan_progress'
        managed = True

    def __str__(self):
        return f"UserPlanProgress({self.plan_key}, unlocked={self.discount_unlocked})"
