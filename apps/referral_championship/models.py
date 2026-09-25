import json
import random
import string
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.models import User
from apps.agents.models import Agent


class ChampionshipCampaign(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('live', 'Live'),
        ('paused', 'Paused'),
        ('ended', 'Ended'),
        ('archived', 'Archived'),
    ]

    name = models.CharField(max_length=255, default="PadosiAgent Referral Championship")
    slug = models.SlugField(max_length=100, unique=True, default="championship-2026")
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='live')
    is_active = models.BooleanField(default=True)

    # Dynamic pricing configuration
    pricing_config = models.JSONField(default=dict, blank=True, help_text="""
    {
      "digital": {"regular_price": 1999, "campaign_price": 999, "renewal_price": 1999, "name": "Starter's Plan"},
      "professional": {"regular_price": 9999, "campaign_price": 4999, "renewal_price": 9999, "name": "Professional's Plan"},
      "discount_percent": 50
    }
    """)

    # Dynamic unlock conditions
    unlock_config = models.JSONField(default=dict, blank=True, help_text="""
    {
      "min_profile_percent": 80,
      "min_reviews": 10
    }
    """)

    # Dynamic Social & Google Review settings
    social_channels = models.JSONField(default=list, blank=True, help_text="List of social channels to follow")
    google_review_url = models.URLField(max_length=500, blank=True, default="https://g.page/r/padosiagent/review")
    rules = models.TextField(blank=True, default="First valid referral attribution wins. Verified and Paid accounts count as qualifying.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'championship_campaigns'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.status})"

    @classmethod
    def get_current(cls):
        """Retrieve the primary live campaign, or create the default one if missing."""
        campaign = cls.objects.filter(is_active=True).exclude(status__in=['ended', 'archived']).first()
        if not campaign:
            start_dt = timezone.make_aware(timezone.datetime(2026, 9, 15, 0, 0, 0)) if settings.USE_TZ else timezone.datetime(2026, 9, 15, 0, 0, 0)
            end_dt = timezone.make_aware(timezone.datetime(2026, 10, 31, 23, 59, 59)) if settings.USE_TZ else timezone.datetime(2026, 10, 31, 23, 59, 59)
            campaign = cls.objects.create(
                name="PadosiAgent Referral Championship",
                slug="championship-2026",
                start_date=start_dt,
                end_date=end_dt,
                status='live',
                is_active=True,
                pricing_config={
                    "digital": {"regular_price": 1999, "campaign_price": 999, "renewal_price": 1999, "name": "Starter's Plan"},
                    "professional": {"regular_price": 9999, "campaign_price": 4999, "renewal_price": 9999, "name": "Professional's Plan"},
                    "discount_percent": 50
                },
                unlock_config={
                    "min_profile_percent": 80,
                    "min_reviews": 10
                },
                social_channels=[
                    {"platform": "instagram", "name": "Instagram", "url": "https://instagram.com/padosiagent", "icon": "fa-instagram"},
                    {"platform": "facebook", "name": "Facebook", "url": "https://facebook.com/padosiagent", "icon": "fa-facebook-f"}
                ],
                google_review_url="https://g.page/r/padosiagent/review"
            )
            # Create default slabs
            campaign.seed_default_slabs()
        return campaign

    def seed_default_slabs(self):
        """Seed standard slabs: 5, 10, 25, 50, 100, 200, Top 3."""
        defaults = [
            (5, "Membership Fee Back", "100% Membership Fee Back via Amazon or Flipkart Voucher", 'membership_fee_back', 'fa-gift', 999.00, 1),
            (10, "Professional's Plan Free", "Professional's Plan complimentary for 12 months", 'plan_upgrade', 'fa-crown', 9999.00, 2),
            (25, "25g Silver Coin", "Exclusive 25 Gram Minted Silver Coin dispatched to your address", 'silver', 'fa-coins', 2500.00, 3),
            (50, "1g Gold Coin + Lucky Draw Tier 1", "1 Gram 24K Gold Coin + Entry in Grand Lucky Draw Tier 1", 'gold', 'fa-medal', 7500.00, 4),
            (100, "Solo Domestic Trip + Lucky Draw Tier 2", "Solo Domestic Luxury Trip (flight + stay) + Tier 2 Draw", 'domestic_trip', 'fa-plane', 35000.00, 5),
            (200, "Solo International Trip + Lucky Draw Tier 3", "Solo International Luxury Vacation + Tier 3 Draw", 'international_trip', 'fa-globe-asia', 90000.00, 6),
            (999, "Top 3: Family International Trip", "Grand Family Vacation (2 Adults + 1 Child) for Top 3 Leaders", 'family_trip', 'fa-trophy', 250000.00, 7),
        ]
        for threshold, title, desc, r_type, icon, val, order in defaults:
            ChampionshipRewardSlab.objects.get_or_create(
                campaign=self,
                threshold=threshold,
                defaults={
                    'title': title,
                    'description': desc,
                    'reward_type': r_type,
                    'badge_icon': icon,
                    'value': val,
                    'order': order,
                    'is_active': True,
                    'dispatch_date_default': timezone.datetime(2026, 12, 15).date()
                }
            )

    @property
    def days_left(self):
        now = timezone.now()
        end = self.end_date
        if end is None:
            return 0
        if timezone.is_naive(end):
            end = timezone.make_aware(end)
        if timezone.is_naive(now):
            now = timezone.make_aware(now)
        if now >= end:
            return 0
        diff = (end - now).total_seconds()
        return max(0, int(diff // 86400))


class ChampionshipParticipant(models.Model):
    campaign = models.ForeignKey(ChampionshipCampaign, on_delete=models.CASCADE, related_name='participants')
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='championship_participations', db_constraint=False)
    referral_id = models.CharField(max_length=50, unique=True, db_index=True)
    is_unlocked = models.BooleanField(default=False)
    profile_completed_at = models.DateTimeField(null=True, blank=True)
    reviews_completed_at = models.DateTimeField(null=True, blank=True)

    qualifying_referrals_count = models.IntegerField(default=0, db_index=True)
    current_rank = models.IntegerField(default=0, db_index=True)
    last_qualification_time = models.DateTimeField(null=True, blank=True)

    is_fraud_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'championship_participants'
        unique_together = ('campaign', 'agent')
        ordering = ['-qualifying_referrals_count', 'last_qualification_time']

    def __str__(self):
        return f"{self.agent.fullname or self.agent.email} ({self.referral_id}) - {self.qualifying_referrals_count} refs"

    @classmethod
    def get_or_create_for_agent(cls, agent, campaign=None):
        if not campaign:
            campaign = ChampionshipCampaign.get_current()

        participant = cls.objects.filter(agent=agent, campaign=campaign).first()
        if participant:
            return participant

        # Generate unique referral code with format PA-XXXXXX
        while True:
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            ref_id = f"PA-{suffix}"
            if not cls.objects.filter(referral_id=ref_id).exists():
                break

        participant = cls.objects.create(
            campaign=campaign,
            agent=agent,
            referral_id=ref_id,
            is_unlocked=False,
            qualifying_referrals_count=0
        )
        return participant


class ChampionshipReferral(models.Model):
    STATE_CHOICES = [
        ('started', 'Started'),
        ('submitted', 'Submitted'),
        ('verification_pending', 'Verification Pending'),
        ('verified', 'Verified'),
        ('plan_selected', 'Plan Selected'),
        ('payment_pending', 'Payment Pending'),
        ('paid', 'Paid'),
        ('active', 'Active'),
        ('refunded', 'Refunded'),
        ('cancelled', 'Cancelled'),
        ('fraud_blocked', 'Fraud Blocked'),
    ]

    campaign = models.ForeignKey(ChampionshipCampaign, on_delete=models.CASCADE, related_name='referrals')
    referrer = models.ForeignKey(ChampionshipParticipant, on_delete=models.CASCADE, related_name='referrals')
    referred_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='championship_attributions', db_constraint=False)
    
    referral_id = models.CharField(max_length=50, db_index=True)
    session_id = models.CharField(max_length=255, blank=True, null=True)
    utm_params = models.JSONField(default=dict, blank=True)
    registration_state = models.CharField(max_length=50, choices=STATE_CHOICES, default='started')
    is_qualifying = models.BooleanField(default=False, db_index=True)
    qualified_at = models.DateTimeField(null=True, blank=True)
    fraud_flag = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'championship_referrals'
        ordering = ['-created_at']

    def __str__(self):
        return f"Ref by {self.referrer.referral_id} -> {self.referred_agent} [{self.registration_state}]"


class ChampionshipRewardSlab(models.Model):
    REWARD_TYPES = [
        ('membership_fee_back', 'Membership Fee Back'),
        ('plan_upgrade', 'Plan Upgrade (Pro 12M)'),
        ('silver', '25g Silver Coin'),
        ('gold', '1g Gold Coin'),
        ('domestic_trip', 'Solo Domestic Trip'),
        ('international_trip', 'Solo International Trip'),
        ('lucky_draw_tier1', 'Lucky Draw Tier 1'),
        ('lucky_draw_tier2', 'Lucky Draw Tier 2'),
        ('lucky_draw_tier3', 'Lucky Draw Tier 3'),
        ('family_trip', 'Family International Trip (Top 3)'),
        ('custom', 'Custom Reward'),
    ]

    campaign = models.ForeignKey(ChampionshipCampaign, on_delete=models.CASCADE, related_name='reward_slabs')
    threshold = models.IntegerField(help_text="Referrals needed to unlock this slab")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    reward_type = models.CharField(max_length=50, choices=REWARD_TYPES)
    badge_icon = models.CharField(max_length=100, default='fa-gift')
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    winner_limit = models.IntegerField(default=0, help_text="0 means unlimited")
    dispatch_date_default = models.DateField(null=True, blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'championship_reward_slabs'
        ordering = ['threshold', 'order']

    def __str__(self):
        return f"{self.threshold} Referrals: {self.title}"


class ChampionshipRewardClaim(models.Model):
    STATUS_CHOICES = [
        ('locked', 'Locked'),
        ('unlocked', 'Unlocked'),
        ('verification', 'Verification'),
        ('approved', 'Approved'),
        ('processing', 'Processing'),
        ('dispatched', 'Dispatched'),
        ('delivered', 'Delivered'),
        ('redeemed', 'Redeemed'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    participant = models.ForeignKey(ChampionshipParticipant, on_delete=models.CASCADE, related_name='claims')
    reward_slab = models.ForeignKey(ChampionshipRewardSlab, on_delete=models.CASCADE, related_name='claims')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='unlocked')
    claim_data = models.JSONField(default=dict, blank=True, help_text="Stores voucher provider (amazon/flipkart), address, etc.")
    
    courier_name = models.CharField(max_length=100, blank=True, null=True)
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    dispatch_date = models.DateField(null=True, blank=True)
    delivered_date = models.DateField(null=True, blank=True)
    admin_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'championship_reward_claims'
        unique_together = ('participant', 'reward_slab')
        ordering = ['-created_at']

    def __str__(self):
        return f"Claim: {self.participant.referral_id} - {self.reward_slab.title} [{self.status}]"


class ChampionshipSocialAction(models.Model):
    session_id = models.CharField(max_length=255, db_index=True)
    participant = models.ForeignKey(ChampionshipParticipant, on_delete=models.SET_NULL, null=True, blank=True)
    platform = models.CharField(max_length=50) # 'instagram', 'facebook'
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'championship_social_actions'


class ChampionshipScratchUnlock(models.Model):
    session_id = models.CharField(max_length=255, db_index=True)
    draft_id = models.IntegerField(null=True, blank=True)
    is_revealed = models.BooleanField(default=False)
    revealed_discount_pct = models.IntegerField(default=25)
    final_unlocked_pct = models.IntegerField(default=50)
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'championship_scratch_unlocks'


class ChampionshipGoogleReviewLog(models.Model):
    session_id = models.CharField(max_length=255, db_index=True)
    prompt_shown_at = models.DateTimeField(auto_now_add=True)
    link_clicked_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'championship_google_review_logs'


class ChampionshipFraudFlag(models.Model):
    STATUS_CHOICES = [
        ('flagged', 'Flagged'),
        ('suspended', 'Suspended'),
        ('rejected', 'Rejected'),
        ('reversed', 'Reversed'),
        ('restored', 'Restored'),
        ('blocked', 'Blocked'),
    ]

    participant = models.ForeignKey(ChampionshipParticipant, on_delete=models.CASCADE, related_name='fraud_flags')
    referral = models.ForeignKey(ChampionshipReferral, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='flagged')
    flagged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'championship_fraud_flags'


class ChampionshipAuditLog(models.Model):
    campaign = models.ForeignKey(ChampionshipCampaign, on_delete=models.SET_NULL, null=True, blank=True)
    admin_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    old_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'championship_audit_logs'
        ordering = ['-created_at']


class ChampionshipLeaderboardCache(models.Model):
    campaign = models.ForeignKey(ChampionshipCampaign, on_delete=models.CASCADE)
    participant = models.ForeignKey(ChampionshipParticipant, on_delete=models.CASCADE)
    rank = models.IntegerField(db_index=True)
    referral_count = models.IntegerField(db_index=True)
    tie_breaker_ts = models.DateTimeField(null=True, blank=True)
    is_frozen = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'championship_leaderboard_cache'
        unique_together = ('campaign', 'participant')
        ordering = ['rank']
