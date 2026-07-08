from django.test.runner import DiscoverRunner
from django.conf import settings
from django.db import connections
from django.db.models.options import Options

class ManagedModelsTestRunner(DiscoverRunner):
    """
    Test runner that forces all Django models to be managed = True during tests,
    and swaps the default database to an in-memory SQLite database to avoid MySQL-specific setup errors.
    """
    def __init__(self, *args, **kwargs):
        # Swap database to SQLite in-memory for tests
        settings.TESTING = True
        db_config = dict(settings.DATABASES['default'])
        db_config['ENGINE'] = 'django.db.backends.sqlite3'
        db_config['NAME'] = ':memory:'
        
        if 'TEST' not in db_config or not isinstance(db_config['TEST'], dict):
            db_config['TEST'] = {}
        db_config['TEST']['NAME'] = ':memory:'
        
        settings.DATABASES['default'] = db_config
        # Update connections dictionary
        connections.databases['default'] = settings.DATABASES['default']
        
        # Clear the cached connection instance if it was already initialized
        try:
            connections['default'].close()
            # Clear from the thread local _connections object
            if hasattr(connections._connections, 'default'):
                delattr(connections._connections, 'default')
        except Exception:
            pass

        # Force Options.managed to always return True for tests, with a dummy setter to avoid AttributeError
        Options.managed = property(fget=lambda self: True, fset=lambda self, value: None)

        super().__init__(*args, **kwargs)

    def setup_test_environment(self, **kwargs):
        from django.apps import apps
        for model in apps.get_models():
            model._meta.managed = True
            
        super().setup_test_environment(**kwargs)
