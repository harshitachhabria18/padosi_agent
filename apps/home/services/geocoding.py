import re
import time
import logging
import requests
from django.core.cache import cache
from apps.home.models import Pincode, PincodeCache
from apps.home.services.distance import DistanceService

logger = logging.getLogger(__name__)

class GeocodingService:
    USER_AGENT = 'PadosiAgent/2.0 (padosiagent.com; contact@padosiagent.com)'
    NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
    REVERSE_URL = 'https://nominatim.openstreetmap.org/reverse'
    TIMEOUT_SEC = 5

    def resolve_coordinates(self, pincode):
        """
        Resolve a 6-digit Indian pincode to coordinates.
        Returns {'lat': float, 'lng': float, 'display_name': str} or None.
        """
        pincode = str(pincode).strip()

        # Strict validation — must be exactly 6 digits, no leading zero
        if not re.match(r'^[1-9]\d{5}$', pincode):
            logger.warning(f"GeocodingService: Invalid pincode format rejected: {pincode}")
            return None

        # ─── Step 1: Check pincode_cache table ────────────────────────────────
        cached = PincodeCache.get_coordinates(pincode)
        if cached:
            dn = cached.get('display_name') or ''
            # If display name is a placeholder, try to resolve a better one but keep coords
            if not dn or re.match(r'^(Area|Region)\s+\d', dn, re.IGNORECASE):
                pass  # Coords are good, but name needs upgrading — continue
            else:
                return cached

        # ─── Step 2: Check existing pincodes table ────────────────────────────
        try:
            existing = Pincode.objects.filter(
                pincode=pincode,
                latitude__isnull=False,
                longitude__isnull=False
            ).first()

            if existing:
                raw_name = existing.office_name or existing.district or ''
                is_placeholder = bool(re.match(r'^(Area|Region)\s+\d', raw_name, re.IGNORECASE))

                if not is_placeholder and raw_name:
                    display_name = Pincode.format_location_name(existing.office_name, existing.district, existing.division)
                    coords = {
                        'lat': float(existing.latitude),
                        'lng': float(existing.longitude),
                        'display_name': display_name
                    }
                    PincodeCache.store_coordinates(pincode, coords['lat'], coords['lng'], coords['display_name'])
                    return coords

                if not cached:
                    cached = {
                        'lat': float(existing.latitude),
                        'lng': float(existing.longitude),
                        'display_name': None
                    }
        except Exception as e:
            logger.warning(f"GeocodingService: pincodes lookup failed: {e}")

        # ─── Step 3: Lookup via postalpincode.in and geocode place name ─────
        postal_result = self.call_postal_pincode_api(pincode)
        if postal_result:
            PincodeCache.store_coordinates(pincode, postal_result['lat'], postal_result['lng'], postal_result.get('display_name'))
            return postal_result

        # ─── Step 4: Call Nominatim API ──────────────────────────
        api_result = self.call_nominatim_with_retry(pincode)
        if api_result:
            PincodeCache.store_coordinates(pincode, api_result['lat'], api_result['lng'], api_result.get('display_name'))
            return api_result

        # ─── Step 5: Regional hardcoded fallback ──────────────────────────────
        fallback = DistanceService.get_hardcoded_coordinates(pincode)
        if fallback:
            coords = {
                'lat': fallback['lat'],
                'lng': fallback['lng'],
                'display_name': self.resolve_state_from_pincode(pincode) + f" - {pincode}"
            }
            PincodeCache.store_coordinates(pincode, coords['lat'], coords['lng'], coords['display_name'])
            return coords

        # ─── Step 6: Return cached coords if all APIs failed ──────────────────
        if cached:
            logger.info(f"GeocodingService: Returning cached coords for {pincode} (APIs failed for display_name).")
            return cached

        logger.error(f"GeocodingService: Could not resolve pincode {pincode} via any method.")
        return None

    def call_nominatim_with_retry(self, pincode, max_retries=2):
        """
        Call Nominatim with retry logic and simple rate limiting.
        """
        for attempt in range(max_retries + 1):
            # Check rate limit key (OSM policy: 1 req/sec)
            rate_limit_key = 'nominatim_api_rate_limit'
            if cache.get(rate_limit_key):
                time.sleep(1.0)
            
            cache.set(rate_limit_key, True, timeout=1)

            try:
                headers = {'User-Agent': self.USER_AGENT}
                params = {
                    'postalcode': pincode,
                    'country': 'India',
                    'format': 'json',
                    'limit': 1,
                    'addressdetails': 0
                }
                response = requests.get(self.NOMINATIM_URL, params=params, headers=headers, timeout=self.TIMEOUT_SEC)
                if response.status_code != 200:
                    logger.warning(f"GeocodingService: Nominatim returned HTTP {response.status_code} for pincode {pincode}")
                    continue

                data = response.json()
                if not data:
                    return self.call_nominatim_alternative(pincode)

                item = data[0]
                display_name = item.get('display_name', '')
                if 'India' not in display_name:
                    logger.warning(f"GeocodingService: Nominatim result for {pincode} not in India: {display_name}")
                    return self.call_nominatim_alternative(pincode)

                lat = float(item.get('lat', 0))
                lng = float(item.get('lon', 0))

                if not self.is_within_india(lat, lng):
                    logger.warning(f"GeocodingService: Coordinates {lat},{lng} outside India for pincode {pincode}")
                    return None

                return {
                    'lat': round(lat, 7),
                    'lng': round(lng, 7),
                    'display_name': self.extract_area_name(display_name)
                }

            except Exception as e:
                logger.error(f"GeocodingService: Nominatim attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    time.sleep(1.0)

        return None

    def call_nominatim_alternative(self, pincode):
        """
        Alternative Nominatim query query="pincode, India" as fallback.
        """
        try:
            headers = {'User-Agent': self.USER_AGENT}
            params = {
                'q': f"{pincode}, India",
                'format': 'json',
                'limit': 1
            }
            response = requests.get(self.NOMINATIM_URL, params=params, headers=headers, timeout=self.TIMEOUT_SEC)
            if response.status_code != 200:
                return None

            data = response.json()
            if not data:
                return None

            item = data[0]
            lat = float(item.get('lat', 0))
            lng = float(item.get('lon', 0))

            if not self.is_within_india(lat, lng):
                return None

            display_name = item.get('display_name', '')
            return {
                'lat': round(lat, 7),
                'lng': round(lng, 7),
                'display_name': self.extract_area_name(display_name)
            }
        except Exception as e:
            logger.error(f"GeocodingService: Alternative Nominatim call failed: {e}")
            return None

    def call_postal_pincode_api(self, pincode):
        """
        Call postalpincode.in API to get place name and geocode it via Nominatim.
        """
        try:
            url = f"https://api.postalpincode.in/pincode/{pincode}"
            response = requests.get(url, timeout=self.TIMEOUT_SEC)
            if response.status_code != 200:
                return None

            data = response.json()
            if not data or data[0].get('Status') != 'Success' or not data[0].get('PostOffice'):
                return None

            post_offices = data[0]['PostOffice']
            post_office = None
            for po in post_offices:
                if po.get('DeliveryStatus') == 'Delivery':
                    post_office = po
                    break
            if not post_office:
                post_office = post_offices[0]

            name = post_office.get('Name', '')
            district = post_office.get('District', '')
            state = post_office.get('State', '')

            if not name:
                return None

            # Now geocode this place name via Nominatim
            query = f"{name}, {district}, {state}, India"
            headers = {'User-Agent': self.USER_AGENT}
            params = {
                'q': query,
                'format': 'json',
                'limit': 1
            }
            nominatim_resp = requests.get(self.NOMINATIM_URL, params=params, headers=headers, timeout=self.TIMEOUT_SEC)
            if nominatim_resp.status_code == 200:
                res_data = nominatim_resp.json()
                if res_data:
                    item = res_data[0]
                    lat = float(item.get('lat', 0))
                    lng = float(item.get('lon', 0))
                    if self.is_within_india(lat, lng):
                        return {
                            'lat': round(lat, 7),
                            'lng': round(lng, 7),
                            'display_name': Pincode.format_location_name(name, district, post_office.get('Division'))
                        }

        except Exception as e:
            logger.error(f"GeocodingService: PostalPincode API failed: {e}")

        return None

    def is_within_india(self, lat, lng):
        return (6.0 <= lat <= 37.5) and (68.0 <= lng <= 97.5)

    def extract_area_name(self, display_name):
        if not display_name:
            return None
        parts = [p.strip() for p in display_name.split(',')]
        # Remove digits, 'India', and very short strings
        filtered = [p for p in parts if not re.match(r'^\d+$', p) and p != 'India' and len(p) > 2]
        if not filtered:
            return None
        return ', '.join(filtered[:2])

    def reverse_geocode(self, lat, lng):
        """
        Reverse geocode coordinates to a human-readable area name.
        """
        cache_key = f'rev_geo_nominatim_{round(lat, 3)}_{round(lng, 3)}'
        cached_val = cache.get(cache_key)
        if cached_val:
            return cached_val

        try:
            headers = {'User-Agent': self.USER_AGENT}
            params = {
                'lat': lat,
                'lon': lng,
                'format': 'json',
                'zoom': 14
            }
            response = requests.get(self.REVERSE_URL, params=params, headers=headers, timeout=self.TIMEOUT_SEC)
            if response.status_code != 200:
                return None

            res = response.json()
            address = res.get('address', {})
            logger.info(f"Reverse Geocode Result for {lat},{lng}: {address}")

            specific = (address.get('suburb') or 
                        address.get('neighbourhood') or 
                        address.get('residential') or 
                        address.get('industrial') or 
                        address.get('city_district') or 
                        address.get('town') or 
                        address.get('village') or 
                        address.get('hamlet'))

            city = (address.get('city') or 
                    address.get('city_district') or 
                    address.get('district') or 
                    address.get('state_district') or 
                    address.get('county'))

            if specific and city and specific.lower() != city.lower():
                result = f"{specific}, {city}"
            else:
                result = specific or city or address.get('state')

            if result:
                cache.set(cache_key, result, timeout=86400)
                return result

        except Exception as e:
            logger.warning(f"GeocodingService: Reverse geocode failed for {lat},{lng}: {e}")

        return None

    @staticmethod
    def resolve_state_from_pincode(pincode):
        prefix2 = pincode[:2]
        state_map = {
            '11': 'Delhi', '12': 'Haryana', '13': 'Haryana', '14': 'Punjab', '15': 'Punjab',
            '16': 'Chandigarh', '17': 'Himachal Pradesh', '18': 'Jammu & Kashmir', '19': 'Jammu & Kashmir',
            '20': 'Uttar Pradesh', '21': 'Uttar Pradesh', '22': 'Uttar Pradesh', '23': 'Uttar Pradesh',
            '24': 'Uttar Pradesh', '25': 'Uttar Pradesh', '26': 'Uttar Pradesh', '27': 'Uttar Pradesh',
            '28': 'Uttar Pradesh', '30': 'Rajasthan', '31': 'Rajasthan', '32': 'Rajasthan',
            '33': 'Rajasthan', '34': 'Rajasthan', '36': 'Gujarat', '37': 'Gujarat', '38': 'Gujarat',
            '39': 'Gujarat', '40': 'Maharashtra', '41': 'Maharashtra', '42': 'Maharashtra',
            '43': 'Maharashtra', '44': 'Maharashtra', '45': 'Madhya Pradesh', '46': 'Madhya Pradesh',
            '47': 'Madhya Pradesh', '48': 'Madhya Pradesh', '49': 'Chhattisgarh', '50': 'Telangana',
            '51': 'Andhra Pradesh', '52': 'Andhra Pradesh', '53': 'Andhra Pradesh', '56': 'Karnataka',
            '57': 'Karnataka', '58': 'Karnataka', '59': 'Karnataka', '60': 'Tamil Nadu',
            '61': 'Tamil Nadu', '62': 'Tamil Nadu', '63': 'Tamil Nadu', '64': 'Tamil Nadu',
            '67': 'Kerala', '68': 'Kerala', '69': 'Kerala', '70': 'West Bengal', '71': 'West Bengal',
            '72': 'West Bengal', '73': 'West Bengal', '74': 'West Bengal', '75': 'Odisha',
            '76': 'Odisha', '77': 'Odisha', '78': 'Assam', '79': 'North Eastern', '80': 'Bihar',
            '81': 'Bihar', '82': 'Bihar', '83': 'Jharkhand', '84': 'Jharkhand', '85': 'Jharkhand',
        }
        if prefix2 in state_map:
            return state_map[prefix2]

        prefix1 = pincode[:1]
        region_map = {
            '1': 'Delhi', '2': 'Uttar Pradesh', '3': 'Gujarat', '4': 'Maharashtra',
            '5': 'Karnataka', '6': 'Tamil Nadu', '7': 'West Bengal', '8': 'Bihar',
        }
        return region_map.get(prefix1, 'Gujarat')
