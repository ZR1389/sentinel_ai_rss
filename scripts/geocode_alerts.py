import os
import time
from geopy.geocoders import Nominatim
from db_utils import fetch_all, execute

geolocator = Nominatim(user_agent="sentinel-geocoder")

def geocode(city, country):
    try:
        loc = geolocator.geocode(f"{city}, {country}", timeout=5)
        if loc:
            return loc.latitude, loc.longitude
    except Exception:
        time.sleep(1)
    return None, None

alerts = fetch_all("SELECT uuid, city, country FROM alerts WHERE latitude IS NULL AND city IS NOT NULL AND country IS NOT NULL LIMIT 1000")
for a in alerts:
    lat, lon = geocode(a['city'], a['country'])
    if lat and lon:
        execute("UPDATE alerts SET latitude=%s, longitude=%s WHERE uuid=%s", (lat, lon, a['uuid']))
        print(f"Geocoded {a['city']}, {a['country']} -> {lat}, {lon}")
        time.sleep(0.5)