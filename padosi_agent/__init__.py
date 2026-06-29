# Monkey patch to bypass strict MariaDB/MySQL database version check in Django 6.x
from django.db.backends.base.base import BaseDatabaseWrapper
BaseDatabaseWrapper.check_database_version_supported = lambda self: None
