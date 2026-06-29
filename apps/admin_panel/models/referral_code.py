from django.db import models
from apps.agents.models import Agent
from django.contrib.auth.models import User
import random
import string

class ReferralCode(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='referral_codes')
    distributor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='distributor_referral_codes', db_column='distributor_id')
    code = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    clicks = models.IntegerField(default=0)
    total_referrals = models.IntegerField(default=0)
    pending_referrals = models.IntegerField(default=0)
    reward_discount_percent = models.IntegerField(default=0)
    reward_claimed = models.BooleanField(default=False)
    reward_type = models.CharField(max_length=255, blank=True, null=True)
    reward_claimed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'referral_codes'
        managed = False

    def __str__(self):
        return f"ReferralCode({self.code}, agent={self.agent})"

    @staticmethod
    def tiers():
        return [
            {'min': 5,  'max': 9,  'reward': 'discount_25', 'label': '25% Discount',               'discount': 25},
            {'min': 10, 'max': 14, 'reward': 'discount_50', 'label': '50% Discount',               'discount': 50},
            {'min': 15, 'max': 999999, 'reward': 'pro_plan_1rs', 'label': 'Professional Plan @ ₹1', 'discount': 100},
        ]

    def currentTier(self):
        for tier in reversed(self.tiers()):
            if self.total_referrals >= tier['min']:
                return tier
        return None

    def nextTier(self):
        for tier in self.tiers():
            if self.total_referrals < tier['min']:
                return tier
        return None

    @classmethod
    def generateForAgent(cls, agent):
        existing = cls.objects.filter(agent_id=agent.id).first()
        if existing:
            return existing

        base_name = agent.fullname or 'AGENT'
        clean_name = ''.join(c for c in base_name.upper() if c.isalnum())
        base = clean_name[:4]
        if len(base) < 2:
            base = 'REF'

        while True:
            random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            code = f"{base}{random_suffix}"
            if not cls.objects.filter(code=code).exists():
                break

        ref_code = cls.objects.create(
            agent=agent,
            code=code,
            is_active=True
        )
        return ref_code
