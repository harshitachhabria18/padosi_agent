from django.contrib import admin
from .models.homepage import (
    HomePageSettings, HeroTrustBadge, HeroStatistic, HeroProductTile,
    HeroSlide, DidYouKnowSlide, QuickPickItem, WhyChooseCard, HowItWorksStep
)

# Singleton Model Admin
@admin.register(HomePageSettings)
class HomePageSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not HomePageSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        return False

class SortableAdminMixin:
    list_display = ('__str__', 'order')
    list_editable = ('order',)
    ordering = ('order',)

@admin.register(HeroTrustBadge)
class HeroTrustBadgeAdmin(SortableAdminMixin, admin.ModelAdmin):
    pass

@admin.register(HeroStatistic)
class HeroStatisticAdmin(SortableAdminMixin, admin.ModelAdmin):
    pass

@admin.register(HeroProductTile)
class HeroProductTileAdmin(SortableAdminMixin, admin.ModelAdmin):
    pass

@admin.register(HeroSlide)
class HeroSlideAdmin(SortableAdminMixin, admin.ModelAdmin):
    pass

@admin.register(DidYouKnowSlide)
class DidYouKnowSlideAdmin(SortableAdminMixin, admin.ModelAdmin):
    pass

@admin.register(QuickPickItem)
class QuickPickItemAdmin(SortableAdminMixin, admin.ModelAdmin):
    pass

@admin.register(WhyChooseCard)
class WhyChooseCardAdmin(SortableAdminMixin, admin.ModelAdmin):
    pass

@admin.register(HowItWorksStep)
class HowItWorksStepAdmin(SortableAdminMixin, admin.ModelAdmin):
    pass
