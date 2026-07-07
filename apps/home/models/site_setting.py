import json
from django.db import models
from django.core.cache import cache

class SiteSetting(models.Model):
    key = models.CharField(max_length=255, unique=True)
    value = models.TextField(blank=True, null=True)
    group = models.CharField(max_length=100, default='general')

    class Meta:
        db_table = 'site_settings'

    CACHE_KEY = 'site_settings_all'

    def __str__(self):
        return f"{self.key}: {self.value}"

    @classmethod
    def get_value(cls, key, default=None):
        settings = cache.get(cls.CACHE_KEY)
        if settings is None:
            settings = {s.key: s.value for s in cls.objects.all()}
            cache.set(cls.CACHE_KEY, settings, timeout=None)

        if key in settings:
            val = settings[key]
            if not val:
                return default
            
            # Auto decode JSON if it looks like one
            if isinstance(val, str) and val.strip().startswith(('{', '[')):
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    pass
            return val
        return default

    @classmethod
    def set_value(cls, key, value, group='general'):
        if isinstance(value, (dict, list)):
            db_value = json.dumps(value)
        else:
            db_value = str(value)

        cls.objects.update_or_create(
            key=key,
            defaults={'value': db_value, 'group': group}
        )
        cls.flush_cache()

    @classmethod
    def flush_cache(cls):
        cache.delete(cls.CACHE_KEY)
        cache.delete('footer_settings_data')

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver(post_save, sender=SiteSetting)
@receiver(post_delete, sender=SiteSetting)
def clear_site_settings_cache(sender, instance, **kwargs):
    SiteSetting.flush_cache()

