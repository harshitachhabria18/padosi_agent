import os
import django
import sys

sys.path.append(r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")
django.setup()

from apps.home.services.geocoding import GeocodingService
from apps.home.services.distance import DistanceService
from apps.home.models import PincodeCache, Pincode
from django.core.cache import cache

pincode = "380008"

print("--- Cache Check ---")
print("Cache geocode_pincode_380008:", cache.get(f"geocode_pincode_{pincode}"))

print("\n--- DB Check ---")
p = Pincode.objects.filter(pincode=pincode, latitude__isnull=False, longitude__isnull=False).first()
if p:
    print(f"Pincode table: lat={p.latitude}, lng={p.longitude}, name={p.office_name}")
else:
    print("Pincode table: Not found")

print("\n--- GeocodingService ---")
svc = GeocodingService()
res1 = svc.resolve_coordinates(pincode)
print("GeocodingService result:", res1)

print("\n--- DistanceService ---")
res2 = DistanceService.get_pincode_coordinates(pincode)
print("DistanceService result:", res2)

print("\n--- Hardcoded Fallback ---")
res3 = DistanceService.get_hardcoded_coordinates(pincode)
print("Hardcoded result:", res3)
