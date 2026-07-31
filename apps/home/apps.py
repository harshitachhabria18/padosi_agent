from django.apps import AppConfig

class HomeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.home'

    def ready(self):
        import os
        # [PRODUCTION READINESS FLAG]
        # WARNING: The RUN_MAIN environment variable is ONLY set by Django's manage.py runserver autoreloader.
        # In a real production deployment (e.g., gunicorn, uwsgi, daphne), RUN_MAIN is never set!
        # This means the scheduler (and critical jobs like IRDAI sync) will SILENTLY FAIL TO START in production.
        # This guard must be replaced with a robust dev/prod lock before deployment.
        if os.environ.get('RUN_MAIN', None) == 'true':
            from scheduler import start
            start()
