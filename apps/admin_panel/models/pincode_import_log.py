from django.db import models

class PincodeImportLog(models.Model):
    filename = models.CharField(max_length=255)
    status = models.CharField(max_length=50, default='pending')
    total_rows = models.IntegerField(default=0)
    imported_rows = models.IntegerField(default=0)
    skipped_rows = models.IntegerField(default=0)
    failed_rows = models.IntegerField(default=0)
    selected_states = models.JSONField(null=True, blank=True)
    selected_districts = models.JSONField(null=True, blank=True)
    available_states = models.JSONField(null=True, blank=True)
    failed_details = models.JSONField(null=True, blank=True)
    imported_by = models.CharField(max_length=150, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pincode_import_logs'
        managed = False

    def __str__(self):
        return f"{self.filename} - {self.status}"
