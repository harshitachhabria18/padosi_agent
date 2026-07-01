from django.db import models

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

    # Step 2 — Profile Details / Professional Details
    photo = models.ImageField(upload_to='agent_photos/', null=True, blank=True)
    about = models.TextField(blank=True, default='')
    languages = models.JSONField(default=list, blank=True)  # e.g. ["Hindi","English"]
    certifications = models.CharField(max_length=200, blank=True, default='')

    # Step 2 Professional Details matching RegisterStep2Request
    license_number = models.CharField(max_length=255, blank=True, default='')
    pan_number = models.CharField(max_length=20, blank=True, default='')
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


class PromoCode(models.Model):
    """
    Django representation of Laravel's promo_codes table.
    Set to managed = False because the table is managed by Laravel/migrations.
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
        managed = False

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
    email_verified_at = models.DateTimeField(null=True, blank=True)
    mobile = models.CharField(max_length=20)
    user_types = models.JSONField(default=list, blank=True)
    insurance_companies = models.JSONField(default=list, blank=True)
    experience_range = models.CharField(max_length=50, blank=True, default='')
    client_base = models.CharField(max_length=50, blank=True, default='')
    registration_step = models.IntegerField(default=1)
    status = models.CharField(max_length=50, default='incomplete')
    plan_type = models.CharField(max_length=50, blank=True, default='')
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    upgrade_discount_percent = models.IntegerField(default=0)
    referred_by_code = models.CharField(max_length=50, blank=True, default='')
    referral_reward_type = models.CharField(max_length=50, blank=True, default='')
    agent_pincode = models.CharField(max_length=6, blank=True, default='')
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    badge = models.CharField(max_length=255, blank=True, default='')
    admin_notes = models.TextField(blank=True, default='')
    event_id = models.IntegerField(null=True, blank=True)
    registration_draft = models.JSONField(null=True, blank=True)
    distributor_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    serviceableCities = models.ManyToManyField('City', db_table='agent_serviceable_cities', blank=True, related_name='agents')

    class Meta:
        db_table = 'agents'
        managed = False

    def __str__(self):
        return f"Agent({self.email}, status={self.status})"

    def isOnFreeTrial(self):
        from django.utils import timezone
        return self.plan_type == 'free_trial' and self.trial_ends_at and self.trial_ends_at > timezone.now()

    def isTrialExpired(self):
        from django.utils import timezone
        return self.plan_type == 'free_trial' and self.trial_ends_at and self.trial_ends_at <= timezone.now()

    @property
    def activeSubscription(self):
        from django.utils import timezone
        return self.subscriptions.filter(status='active', expires_at__gt=timezone.now()).first()

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
        return self.careerTimelines.all().order_by('-year')

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
        managed = False

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
    pan_number = models.CharField(max_length=20, blank=True, default='')
    license_number = models.CharField(max_length=255, blank=True, default='')
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
    career_highlights = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_profiles'
        managed = False

    def __str__(self):
        return f"Profile({self.agent.email})"

    def save(self, *args, **kwargs):
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
    def profile_photo_url(self):
        path = (self.profile_photo_path or '').strip()
        if not path:
            return '/static/img/avatar-icon.jpg'
        if path.startswith(('http://', 'https://')):
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
        managed = False


class AgentInsuranceSegment(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='insuranceSegments')
    segment_type = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_insurance_segments'
        managed = False


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
        managed = False

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
        managed = False


class AgentProfileView(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='profile_views')
    view_date = models.DateField()
    view_count = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_profile_views'
        managed = False


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
        managed = False


class AgentFamilyLicense(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='familyLicenses')
    full_name = models.CharField(max_length=255)
    relationship = models.CharField(max_length=255)
    license_number = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_family_licenses'
        managed = False


class AgentPortfolio(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='portfolios')
    segment_type = models.CharField(max_length=255)
    primary_companies = models.JSONField(null=True, blank=True)
    secondary_companies = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_portfolios'
        managed = False


class AgentAchievementPhoto(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='achievementPhotos')
    photo_path = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_achievement_photos'
        managed = False

    @property
    def photo_url(self):
        path = (self.photo_path or '').strip()
        if not path:
            return '/static/img/avatar-icon.jpg'
        if path.startswith(('http://', 'https://')):
            return path
        normalized_path = path.replace('\\', '/').lstrip('/')
        from django.conf import settings
        import os
        if os.path.exists(os.path.join(settings.MEDIA_ROOT, normalized_path)):
            return f"/media/{normalized_path}"
        for prefix in ['app/public/', 'public/storage/', 'public/', 'storage/']:
            if normalized_path.startswith(prefix):
                stripped = normalized_path[len(prefix):]
                if os.path.exists(os.path.join(settings.MEDIA_ROOT, stripped)):
                    return f"/media/{stripped}"
                if os.path.exists(os.path.join(settings.MEDIA_ROOT, 'app/public', stripped)):
                    return f"/media/app/public/{stripped}"
                break
        return f"/media/{normalized_path}"


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
        managed = False


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
        managed = False


class AgentCareerTimeline(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='careerTimelines')
    event_type = models.CharField(max_length=255)
    event_text = models.TextField()
    month = models.CharField(max_length=50, blank=True, default='')
    year = models.CharField(max_length=4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_career_timelines'
        managed = False


class AgentDeviceToken(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, db_column='agent_id', related_name='device_tokens')
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=50, null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'agent_device_tokens'
        managed = False

    def __str__(self):
        return f"DeviceToken({self.token[:20]}..., agent={self.agent_id})"


class Event(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    event_date = models.DateField()

    class Meta:
        db_table = 'events'
        managed = False

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
        managed = False

    def __str__(self):
        return f"EditLog(agent={self.agent_id}, step={self.step})"


class BlockedIp(models.Model):
    ip_address = models.CharField(max_length=45, unique=True)
    reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'blocked_ips'
        managed = False

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
        managed = False

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
        managed = False

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






