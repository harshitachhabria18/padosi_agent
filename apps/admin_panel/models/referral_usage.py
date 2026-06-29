from django.db import models
from apps.agents.models import Agent
from django.contrib.auth.models import User
from .referral_code import ReferralCode

class ReferralUsage(models.Model):
    referral_code = models.ForeignKey(ReferralCode, on_delete=models.CASCADE, related_name='usages', db_column='referral_code_id')
    referrer_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='referrals_sent', db_column='referrer_agent_id')
    distributor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='distributor_referrals', db_column='distributor_id')
    referred_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='referral_usage_record', db_column='referred_agent_id')
    referred_agent_name = models.CharField(max_length=255, blank=True, null=True)
    referred_agent_email = models.EmailField(blank=True, null=True)
    referred_agent_mobile = models.CharField(max_length=20, blank=True, null=True)
    status = models.CharField(max_length=50, default='pending')
    signed_up_at = models.DateTimeField(blank=True, null=True)
    converted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'referral_usages'
        managed = False

    def __str__(self):
        return f"ReferralUsage(code={self.referral_code.code}, status={self.status})"
