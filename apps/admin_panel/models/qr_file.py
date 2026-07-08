from django.db import models

class QrFile(models.Model):
    id = models.BigAutoField(primary_key=True)
    unique_code = models.CharField(max_length=255, unique=True)
    filename = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)
    file_size = models.BigIntegerField()
    download_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'qr_files'
        managed = False

    @property
    def formatted_size(self):
        bytes_val = self.file_size
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while bytes_val >= 1024 and i < len(units) - 1:
            bytes_val /= 1024
            i += 1
        return f"{round(bytes_val, 2)} {units[i]}"
