from django.db import models


class Faq(models.Model):
    CATEGORY_CHOICES = [
        ('general', 'General'),
        ('for_customers', 'For Customers'),
        ('for_agents', 'For Agents'),
        ('claims', 'Claims'),
        ('payments', 'Payments'),
    ]

    question   = models.TextField()
    answer     = models.TextField()
    category   = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='general')
    is_active  = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'faqs'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.question[:80]

    def get_category_display_label(self):
        """Return a human-readable category label (replaces Laravel's ucfirst + str_replace)."""
        return dict(self.CATEGORY_CHOICES).get(self.category, self.category.replace('_', ' ').title())
