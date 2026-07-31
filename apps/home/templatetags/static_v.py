import os
from django import template
from django.templatetags.static import static
from django.conf import settings

register = template.Library()

@register.simple_tag
def static_v(path):
    url = static(path)
    file_path = os.path.join(settings.BASE_DIR, 'static', path)
    if os.path.exists(file_path):
        mtime = int(os.path.getmtime(file_path))
        return f"{url}?v={mtime}"
    return url
