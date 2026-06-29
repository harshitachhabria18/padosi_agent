# Rename: `padosiagent` → `padosi_agent` (inner Python package)

## Summary

Renamed the Django project Python package from `padosiagent` (no underscore) to `padosi_agent` (with underscore) to match the outer project directory name.

**Folder renamed:** `django/padosi_agent/padosiagent/` → `django/padosi_agent/padosi_agent/`

---

## Files Modified (20 total)

### 1. Core Django files (5 references in 4 files)

| File | Line | Change |
|------|------|--------|
| `manage.py` | 9 | `'padosiagent.settings'` → `'padosi_agent.settings'` |
| `padosi_agent/wsgi.py` | 14 | `'padosiagent.settings'` → `'padosi_agent.settings'` |
| `padosi_agent/asgi.py` | 14 | `'padosiagent.settings'` → `'padosi_agent.settings'` |
| `padosi_agent/settings.py` | 70 | `ROOT_URLCONF = 'padosiagent.urls'` → `'padosi_agent.urls'` |
| `padosi_agent/settings.py` | 88 | `WSGI_APPLICATION = 'padosiagent.wsgi.application'` → `'padosi_agent.wsgi.application'` |

### 2. Scratch scripts (15 files)

All 15 files in `scratch/` had:
```python
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosiagent.settings')
```
Changed to:
```python
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
```

Files:
- `scratch/check_agent_coords.py`
- `scratch/check_city_filter.py`
- `scratch/check_db_tables.py`
- `scratch/check_matching_users.py`
- `scratch/check_relations.py`
- `scratch/create_media_folders.py`
- `scratch/desc_agent_profiles.py`
- `scratch/desc_users.py`
- `scratch/print_sql.py`
- `scratch/test_combination.py`
- `scratch/test_find_agents.py`
- `scratch/test_find_ahmedabad.py`
- `scratch/test_photo_url.py`
- `scratch/test_select_raw_combo.py`
- `scratch/test_select_related_sql.py`

---

## Not Changed (no impact on functionality)

These contain `padosiagent` as a **brand name, domain, email, or cosmetic comment** — not a Python module reference:

| File | Text | Reason |
|------|------|--------|
| `settings.py` docstring | `"Django settings for padosiagent project."` | Cosmetic comment only |
| `wsgi.py` docstring | `"WSGI config for padosiagent project."` | Cosmetic comment only |
| `asgi.py` docstring | `"ASGI config for padosiagent project."` | Cosmetic comment only |
| `urls.py` docstring | `"URL configuration for padosiagent project."` | Cosmetic comment only |
| `settings.py:97` | `'NAME': 'padosiagent'` | Database name, not a Python import |
| `settings.py:156` | `'noreply@padosiagent.com'` | Email address |
| `settings.py:176` | `'noreply@padosiagent.com'` | Email address |
| `apps/agents/services/brevo.py` | `padosiagent.com` | Website domain in email templates |
| `apps/home/services/geocoding.py` | `'PadosiAgent/2.0 (padosiagent.com;...)'` | HTTP User-Agent string |
| `apps/admin_panel/views/settings.py` | `padosiagent` in SEO keywords | Content string |
| `apps/admin_panel/views/settings.py` | `support@padosiagent.com` | Support email |

---

## Verification

- `python manage.py runserver` starts without errors
- `import padosi_agent.settings` resolves correctly
- `settings.ROOT_URLCONF` → `'padosi_agent.urls'`
- `settings.WSGI_APPLICATION` → `'padosi_agent.wsgi.application'`
- `settings.SETTINGS_MODULE` → `'padosi_agent.settings'`
