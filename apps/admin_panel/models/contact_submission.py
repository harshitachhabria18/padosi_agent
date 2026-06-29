import uuid
from django.db import models


class ContactSubmission(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('replied', 'Replied'),
        ('closed',  'Closed'),
    ]

    reference_id = models.CharField(max_length=50, unique=True, blank=True)
    name         = models.CharField(max_length=100)
    email        = models.EmailField(max_length=100)
    mobile       = models.CharField(max_length=10)
    company      = models.CharField(max_length=100, blank=True, null=True)
    subject      = models.CharField(max_length=100)
    message      = models.TextField()
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contact_submissions'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.reference_id}] {self.name} — {self.subject}"

    def save(self, *args, **kwargs):
        """Auto-generate reference_id before first save (mirrors Laravel's generateReferenceId)."""
        if not self.reference_id:
            self.reference_id = self._generate_reference_id()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_reference_id():
        """Generate a unique reference ID like CS-XXXXXXXX."""
        return f"CS-{uuid.uuid4().hex[:8].upper()}"
