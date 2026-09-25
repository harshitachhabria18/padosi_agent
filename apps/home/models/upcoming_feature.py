from django.db import models


class UpcomingFeature(models.Model):
    PLAN_CHOICES = [
        ('all', 'All Plans (Starter & Professional)'),
        ('starter', "Starter's Plan Only"),
        ('professional', "Professional's Plan Only"),
    ]

    STATUS_BADGE_CHOICES = [
        ('', 'No Badge'),
        ('next_up', 'Next up'),
        ('in_development', 'In development'),
        ('coming_soon', 'Coming soon'),
        ('beta', 'Beta'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    icon = models.CharField(
        max_length=100,
        default='fa-solid fa-wand-magic-sparkles',
        help_text="FontAwesome icon class (e.g. 'fa-solid fa-wand-magic-sparkles')"
    )
    status_badge = models.CharField(
        max_length=50,
        choices=STATUS_BADGE_CHOICES,
        blank=True,
        default=''
    )
    custom_badge_text = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="Optional custom badge text"
    )
    visible_to = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default='all'
    )
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'upcoming_features'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.title

    @property
    def badge_label(self):
        if self.custom_badge_text:
            return self.custom_badge_text.strip()
        if self.status_badge:
            return dict(self.STATUS_BADGE_CHOICES).get(self.status_badge, self.status_badge)
        return ''
