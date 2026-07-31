from django.db import models
from django.utils import timezone
import uuid

class ChatSession(models.Model):
    session_id = models.CharField(max_length=255, unique=True, default=uuid.uuid4)
    is_test_traffic = models.BooleanField(default=False, help_text="Flag to exclude dev/QA sessions from analytics")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session {self.session_id}"

class ChatMessage(models.Model):
    ROLE_CHOICES = (
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
        ('tool', 'Tool'),
    )
    
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(default=timezone.now)
    
    # Store tool call information if applicable
    tool_call_id = models.CharField(max_length=255, blank=True, null=True)
    tool_name = models.CharField(max_length=255, blank=True, null=True)
    agent_cards = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"[{self.role}] {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

class LatencyLog(models.Model):
    endpoint = models.CharField(max_length=255)
    time_to_first_token = models.FloatField(blank=True, null=True)
    total_time = models.FloatField()
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.endpoint} - {self.total_time}s"
