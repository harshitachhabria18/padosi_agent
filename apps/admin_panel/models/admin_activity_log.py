from django.db import models
from django.utils import timezone

class AdminActivityLog(models.Model):
    admin_id = models.IntegerField(null=True, blank=True)
    action = models.CharField(max_length=255)
    model_type = models.CharField(max_length=100, null=True, blank=True)
    model_id = models.IntegerField(null=True, blank=True)
    details = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'admin_activity_logs'

    def __str__(self):
        return f"{self.action} by Admin {self.admin_id} on {self.created_at}"

    @classmethod
    def log(cls, action, model_type=None, model_id=None, details=None, request=None):
        ip = None
        admin_id = None
        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.META.get('REMOTE_ADDR')
            
            admin_id = request.session.get('admin_id')

        return cls.objects.create(
            admin_id=admin_id,
            action=action,
            model_type=model_type,
            model_id=model_id,
            details=details,
            ip_address=ip
        )
