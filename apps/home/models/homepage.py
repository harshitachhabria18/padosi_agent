from django.db import models

class HomePageSettings(models.Model):
    """Singleton model for overall homepage settings."""
    show_dyk = models.BooleanField(default=True, verbose_name="Show Did You Know Section")
    show_quickpicks = models.BooleanField(default=True, verbose_name="Show Quick Picks Section")
    show_why_choose = models.BooleanField(default=True, verbose_name="Show Why Choose Section")
    show_how_it_works = models.BooleanField(default=True, verbose_name="Show How It Works Section")
    show_testimonials = models.BooleanField(default=True, verbose_name="Show Testimonials Section")

    # Hero Section
    hero_heading = models.CharField(max_length=255, default="Find a {Trusted} Insurance Expert in your {Padosi}")
    hero_cta_claim_text = models.CharField(max_length=100, default="Insurance Claims Support")
    hero_cta_claim_url = models.CharField(max_length=255, default="/find-agents?ServiceType=Claim%20Assistance&openFilter=1")
    hero_cta_review_text = models.CharField(max_length=100, default="Insurance Audit")
    hero_cta_review_url = models.CharField(max_length=255, default="/find-agents?ServiceType=Policy%20Review&openFilter=1")
    hero_claims_card_label = models.CharField(max_length=100, default="FIND INSURANCE EXPERTS NEAR ME FOR:")
    hero_claims_card_heading = models.CharField(max_length=255, default="Claims, audits and policy review with local advisors")
    hero_claims_card_text = models.TextField(default="Easy local guidance from verified agents, with real advisor stories and trusted help just a few minutes away.")

    # Section Titles & Text
    dyk_label = models.CharField(max_length=100, default="Did you know?")
    dyk_title = models.CharField(max_length=255, default="Insights from the Padosi network")

    quickpicks_label = models.CharField(max_length=100, default="Quick picks")
    quickpicks_title = models.CharField(max_length=255, default="Also buy / renew shortcuts")
    quickpicks_view_all_text = models.CharField(max_length=100, default="View all products →")
    quickpicks_view_all_url = models.CharField(max_length=255, default="/find-agents?ServiceType=New%20Policy&openFilter=1")

    why_choose_label = models.CharField(max_length=100, default="Why PadosiAgent")
    why_choose_title = models.CharField(max_length=255, default="What makes PadosiAgent one of India's most trusted ways to buy insurance?")
    why_choose_description = models.TextField(default="No spam, no platform fees and only licensed agents — built around your privacy, your time and your money.")
    why_choose_button_text = models.CharField(max_length=100, default="Find My PadosiAgent")
    why_choose_button_url = models.CharField(max_length=255, default="/find-agents?openFilter=1")

    works_label = models.CharField(max_length=100, default="How It Works")
    works_title = models.CharField(max_length=255, default="Find My PadosiAgent in 4 Simple Steps")
    works_subtitle = models.CharField(max_length=255, default="From search to service - it takes just minutes for you")
    works_button_text = models.CharField(max_length=100, default="Find Agent")
    works_button_url = models.CharField(max_length=255, default="/find-agents?openFilter=1")

    testimonials_label = models.CharField(max_length=100, default="Testimonials")
    testimonials_title = models.CharField(max_length=255, default="What Users Say About Their PadosiAgent")
    testimonials_subtitle = models.CharField(max_length=255, default="Real experiences from users who found their PadosiAgent")

    class Meta:
        verbose_name = "Home Page Settings"
        verbose_name_plural = "Home Page Settings"

    def __str__(self):
        return "Global Home Page Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class HeroTrustBadge(models.Model):
    icon = models.CharField(max_length=50, help_text="e.g., check-circle, shield", default="")
    label = models.CharField(max_length=100, default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.label


class HeroStatistic(models.Model):
    label = models.CharField(max_length=100, default="")
    target = models.FloatField(default=0.0)
    suffix = models.CharField(max_length=10, blank=True)
    icon = models.CharField(max_length=50, default="")
    is_large = models.BooleanField(default=False)
    is_decimal = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.label


class HeroProductTile(models.Model):
    label = models.CharField(max_length=100, default="")
    icon = models.CharField(max_length=50, default="")
    url = models.CharField(max_length=255, default="")
    css_class = models.CharField(max_length=50, help_text="e.g., pa-tile-rose", default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.label


class HeroSlide(models.Model):
    icon = models.CharField(max_length=50, default="")
    hero_text = models.CharField(max_length=100, default="")
    tag = models.CharField(max_length=100, default="")
    body = models.TextField(blank=True)
    is_chart = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.hero_text


class DidYouKnowSlide(models.Model):
    icon = models.CharField(max_length=50, default="")
    title = models.CharField(max_length=150, default="")
    body = models.TextField(default="")
    accent_class = models.CharField(max_length=50, help_text="e.g., accent-rose", default="")
    bg_class = models.CharField(max_length=50, help_text="e.g., bg-rose-500", default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.title


class QuickPickItem(models.Model):
    label = models.CharField(max_length=100, default="")
    badge_text = models.CharField(max_length=50, blank=True)
    badge_bg_color = models.CharField(max_length=20, blank=True)
    badge_text_color = models.CharField(max_length=20, blank=True)
    icon_bg_color = models.CharField(max_length=20, default="#fff1f2")
    icon_color = models.CharField(max_length=20, default="#f43f5e")
    icon = models.CharField(max_length=50, default="")
    url = models.CharField(max_length=255, default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.label


class WhyChooseCard(models.Model):
    stat_text = models.CharField(max_length=50, default="")
    caption = models.CharField(max_length=100, default="")
    icon = models.CharField(max_length=50, default="")
    title = models.CharField(max_length=150, default="")
    body = models.TextField(default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.title


class HowItWorksStep(models.Model):
    badge_number = models.CharField(max_length=10, blank=True)
    icon = models.CharField(max_length=50, default="")
    accent_class = models.CharField(max_length=50, default="accent-primary")
    title = models.CharField(max_length=100, default="")
    description = models.CharField(max_length=200, default="")
    tooltip = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.title
