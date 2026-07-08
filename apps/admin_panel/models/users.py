from django.db import models

class User(models.Model):
    id = models.BigAutoField(primary_key=True)
    fullname = models.CharField(max_length=191)
    email = models.CharField(unique=True, max_length=191)
    password = models.CharField(max_length=191)
    custom_invite_message = models.TextField(blank=True, null=True)
    remember_token = models.CharField(max_length=100, blank=True, null=True)
    role = models.CharField(max_length=11)
    status = models.CharField(max_length=9)
    email_verified_at = models.DateTimeField(blank=True, null=True)
    last_login_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'users'
        app_label = 'admin_panel'

    def __str__(self):
        return self.fullname
