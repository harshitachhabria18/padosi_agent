from django.db import models

class Admin(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    role = models.CharField(max_length=191, default='staff')
    permissions = models.JSONField(null=True, blank=True)
    remember_token = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'admins'
        managed = False

    def __str__(self):
        return f"Admin({self.email})"


class SecurityThreatLog(models.Model):
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    event_type = models.CharField(max_length=255)
    url = models.TextField(null=True, blank=True)
    payload = models.TextField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    hacker_name = models.CharField(max_length=191, null=True, blank=True)
    hacker_email = models.CharField(max_length=191, null=True, blank=True)
    hacker_mobile = models.CharField(max_length=191, null=True, blank=True)
    location = models.CharField(max_length=191, null=True, blank=True)
    isp = models.CharField(max_length=191, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'security_threat_logs'
        managed = False

    def __str__(self):
        return f"SecurityThreatLog({self.event_type} - {self.ip_address})"
