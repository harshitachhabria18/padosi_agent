"""
apps/admin_panel/services/site_settings.py

Raw SQL helper to read/write site_settings table.
Mirrors Laravel's SiteSetting::getValue() / SiteSetting::set() behaviour.
"""
import json
from django.db import connection


def get_setting(key, default=None):
    """
    Read a single setting by key.  Auto-decodes JSON blobs (arrays/objects).
    Returns `default` when the key does not exist or the stored value is empty.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT `value` FROM site_settings WHERE `key` = %s LIMIT 1",
            [key],
        )
        row = cursor.fetchone()

    if not row or not row[0]:
        return default

    value = row[0]
    # Auto-decode JSON if the value looks like a JSON array or object
    if isinstance(value, str) and value and value[0] in ('{', '['):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass

    return value


def set_setting(key, value, group='general'):
    """
    Upsert a setting.  Arrays/dicts are JSON-encoded automatically.
    Mirrors Laravel's SiteSetting::set().
    """
    if isinstance(value, (dict, list)):
        value = json.dumps(value)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO site_settings (`key`, `value`, `group`, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE `value` = VALUES(`value`), `group` = VALUES(`group`), updated_at = NOW()
            """,
            [key, value, group],
        )
