from django.db import models
from apps.admin_panel.models.users import User
from apps.agents.models import Agent

class AgentApprovalRequest(models.Model):
    id = models.BigAutoField(primary_key=True)
    insurance = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name='approval_requests', db_column='insurance_id')
    agent = models.ForeignKey(Agent, on_delete=models.DO_NOTHING, related_name='approval_requests', db_column='agent_id')
    action = models.CharField(max_length=50)
    status = models.CharField(max_length=50, default='pending')
    reason = models.TextField(null=True, blank=True)
    admin_note = models.TextField(null=True, blank=True)
    processed_by = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name='processed_requests', null=True, blank=True, db_column='processed_by')
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_approval_requests'
        managed = False

    def is_pending(self):
        return self.status == 'pending'

    def is_approved(self):
        return self.status == 'approved'

    def is_rejected(self):
        return self.status == 'rejected'
