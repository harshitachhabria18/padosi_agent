from django.db import models

class BlacklistedAgent(models.Model):
    sr_no            = models.IntegerField(null=True, blank=True)
    insurer          = models.CharField(max_length=255, null=True, blank=True)
    insurer_type     = models.CharField(max_length=50, null=True, blank=True)
    pan              = models.CharField(max_length=20, null=True, blank=True)
    agent_name       = models.CharField(max_length=255)
    agency_code      = models.CharField(max_length=50, null=True, blank=True)
    blacklisted_date = models.DateField(null=True, blank=True)
    source           = models.CharField(max_length=100, default='IRDAI')
    imported_at      = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'blacklisted_agents'
        ordering = ['agent_name']

    def __str__(self):
        return f"{self.agent_name} — {self.pan}"
