import re
from django.db import models
from django.utils import timezone

class Pincode(models.Model):
    pincode = models.CharField(max_length=10, unique=True)
    office_name = models.CharField(max_length=150)
    district = models.CharField(max_length=100)
    state = models.CharField(max_length=50)
    latitude = models.DecimalField(max_digits=10, decimal_places=8)
    longitude = models.DecimalField(max_digits=10, decimal_places=8)
    division = models.CharField(max_length=100, null=True, blank=True)
    region = models.CharField(max_length=100, null=True, blank=True)
    circle = models.CharField(max_length=100, null=True, blank=True)
    taluk = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pincodes'
        managed = False

    def __str__(self):
        return f"{self.pincode} - {self.office_name}"

    @property
    def formatted_location(self):
        return self.format_location_name(self.office_name, self.district, self.division)

    @staticmethod
    def format_location_name(office_name, district, division=None):
        office = (office_name or '').strip()
        
        # Clean Office Name: remove " SO", " BO", " HO", " GPO", etc.
        clean_office = re.sub(r'\s+(S\.?O\.?|B\.?O\.?|H\.?O\.?|G\.?P\.?O\.?)$', '', office, flags=re.IGNORECASE)
        clean_office = clean_office.title()

        # Clean District / Division
        clean_district = (district or '').strip()
        
        if division:
            # Remove " Division" and " City" (case-insensitive)
            clean_div = re.sub(r'\b(Division|City)\b', '', division, flags=re.IGNORECASE)
            # Normalize spaces
            clean_div = re.sub(r'\s+', ' ', clean_div.strip())
            
            # If we are in Mumbai, replace district with Division (e.g. Mumbai South)
            if 'mumbai' in clean_district.lower():
                clean_district = clean_div
        
        clean_district = clean_district.title()

        # Check sound likeness / metaphone check
        # We can implement a simplified sound check by checking if clean_office starts with/contains clean_district
        if clean_office.lower() == clean_district.lower():
            parts = [clean_office]
        else:
            parts = [p for p in [clean_office, clean_district] if p]

        return ', '.join(parts)


class PincodeCache(models.Model):
    pincode = models.CharField(max_length=10, unique=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=8)
    longitude = models.DecimalField(max_digits=10, decimal_places=8)
    display_name = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'pincode_cache'
        managed = False

    def __str__(self):
        return f"{self.pincode} cached"

    @classmethod
    def get_coordinates(cls, pincode):
        try:
            record = cls.objects.filter(pincode=pincode).first()
            if not record:
                return None
            return {
                'lat': float(record.latitude),
                'lng': float(record.longitude),
                'display_name': record.display_name,
            }
        except Exception:
            return None

    @classmethod
    def store_coordinates(cls, pincode, lat, lng, display_name=None):
        try:
            obj, created = cls.objects.get_or_create(
                pincode=pincode,
                defaults={
                    'latitude': lat,
                    'longitude': lng,
                    'display_name': display_name,
                    'created_at': timezone.now()
                }
            )
            return obj
        except Exception:
            # Fallback for concurrency
            return cls.objects.filter(pincode=pincode).first()
