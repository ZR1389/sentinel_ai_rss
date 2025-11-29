#!/usr/bin/env python3
"""
Expand location_keywords.json with additional cities for better detection accuracy.
Only adds cities that aren't already present to avoid duplicates.
"""

import json
import os

# New cities to add - strategically chosen for global coverage
NEW_CITIES = {
    # Underrepresented countries - adding second cities
    "chiang mai": {"lat": 18.7883, "lon": 98.9853, "country": "thailand", "region": "southeast_asia"},
    "pattaya": {"lat": 12.9236, "lon": 100.8825, "country": "thailand", "region": "southeast_asia"},
    "dodoma": {"lat": -6.1630, "lon": 35.7516, "country": "tanzania", "region": "east_africa"},
    "arusha": {"lat": -3.3869, "lon": 36.6830, "country": "tanzania", "region": "east_africa"},
    "samarkand": {"lat": 39.6270, "lon": 66.9750, "country": "uzbekistan", "region": "central_asia"},
    "bukhara": {"lat": 39.7747, "lon": 64.4286, "country": "uzbekistan", "region": "central_asia"},
    "maracaibo": {"lat": 10.6316, "lon": -71.6400, "country": "venezuela", "region": "south_america"},
    "valencia venezuela": {"lat": 10.1621, "lon": -68.0077, "country": "venezuela", "region": "south_america"},
    "aden": {"lat": 12.7797, "lon": 45.0365, "country": "yemen", "region": "western_asia"},
    "taiz": {"lat": 13.5795, "lon": 44.0207, "country": "yemen", "region": "western_asia"},
    "livingstone": {"lat": -17.8419, "lon": 25.8544, "country": "zambia", "region": "southern_africa"},
    "ndola": {"lat": -12.9587, "lon": 28.6366, "country": "zambia", "region": "southern_africa"},
    "bulawayo": {"lat": -20.1594, "lon": 28.5842, "country": "zimbabwe", "region": "southern_africa"},
    "gweru": {"lat": -19.4500, "lon": 29.8147, "country": "zimbabwe", "region": "southern_africa"},
    "taichung": {"lat": 24.1477, "lon": 120.6736, "country": "taiwan", "region": "east_asia"},
    "kaohsiung": {"lat": 22.6273, "lon": 120.3014, "country": "taiwan", "region": "east_asia"},
    
    # Major missing European cities
    "ghent": {"lat": 51.0500, "lon": 3.7167, "country": "belgium", "region": "western_europe"},
    "gent": {"lat": 51.0500, "lon": 3.7167, "country": "belgium", "region": "western_europe"},
    "liege": {"lat": 50.6292, "lon": 5.5796, "country": "belgium", "region": "western_europe"},
    "bordeaux": {"lat": 44.8378, "lon": -0.5792, "country": "france", "region": "western_europe"},
    "montpellier": {"lat": 43.6108, "lon": 3.8767, "country": "france", "region": "western_europe"},
    "rennes": {"lat": 48.1173, "lon": -1.6778, "country": "france", "region": "western_europe"},
    "düsseldorf": {"lat": 51.2277, "lon": 6.7735, "country": "germany", "region": "western_europe"},
    "dusseldorf": {"lat": 51.2277, "lon": 6.7735, "country": "germany", "region": "western_europe"},
    "dresden": {"lat": 51.0504, "lon": 13.7373, "country": "germany", "region": "western_europe"},
    "hannover": {"lat": 52.3759, "lon": 9.7320, "country": "germany", "region": "western_europe"},
    "hanover": {"lat": 52.3759, "lon": 9.7320, "country": "germany", "region": "western_europe"},
    "nuremberg": {"lat": 49.4521, "lon": 11.0767, "country": "germany", "region": "western_europe"},
    "nürnberg": {"lat": 49.4521, "lon": 11.0767, "country": "germany", "region": "western_europe"},
    "catania": {"lat": 37.5079, "lon": 15.0830, "country": "italy", "region": "southern_europe"},
    "bari": {"lat": 41.1171, "lon": 16.8719, "country": "italy", "region": "southern_europe"},
    "verona": {"lat": 45.4384, "lon": 10.9916, "country": "italy", "region": "southern_europe"},
    "zaragoza": {"lat": 41.6488, "lon": -0.8891, "country": "spain", "region": "southern_europe"},
    "malaga": {"lat": 36.7213, "lon": -4.4214, "country": "spain", "region": "southern_europe"},
    "málaga": {"lat": 36.7213, "lon": -4.4214, "country": "spain", "region": "southern_europe"},
    "braga": {"lat": 41.5518, "lon": -8.4229, "country": "portugal", "region": "southern_europe"},
    "coimbra": {"lat": 40.2033, "lon": -8.4103, "country": "portugal", "region": "southern_europe"},
    "eindhoven": {"lat": 51.4416, "lon": 5.4697, "country": "netherlands", "region": "western_europe"},
    "tilburg": {"lat": 51.5555, "lon": 5.0913, "country": "netherlands", "region": "western_europe"},
    "groningen": {"lat": 53.2194, "lon": 6.5665, "country": "netherlands", "region": "western_europe"},
    "bergen": {"lat": 60.3913, "lon": 5.3221, "country": "norway", "region": "northern_europe"},
    "trondheim": {"lat": 63.4305, "lon": 10.3951, "country": "norway", "region": "northern_europe"},
    "stavanger": {"lat": 58.9700, "lon": 5.7331, "country": "norway", "region": "northern_europe"},
    "malmö": {"lat": 55.6049, "lon": 13.0038, "country": "sweden", "region": "northern_europe"},
    "malmo": {"lat": 55.6049, "lon": 13.0038, "country": "sweden", "region": "northern_europe"},
    "uppsala": {"lat": 59.8586, "lon": 17.6389, "country": "sweden", "region": "northern_europe"},
    "aarhus": {"lat": 56.1629, "lon": 10.2039, "country": "denmark", "region": "northern_europe"},
    "aalborg": {"lat": 57.0488, "lon": 9.9217, "country": "denmark", "region": "northern_europe"},
    "odense": {"lat": 55.4038, "lon": 10.4024, "country": "denmark", "region": "northern_europe"},
    "tampere": {"lat": 61.4991, "lon": 23.7871, "country": "finland", "region": "northern_europe"},
    "turku": {"lat": 60.4518, "lon": 22.2666, "country": "finland", "region": "northern_europe"},
    "oulu": {"lat": 65.0121, "lon": 25.4651, "country": "finland", "region": "northern_europe"},
    "bâle": {"lat": 47.5596, "lon": 7.5886, "country": "switzerland", "region": "western_europe"},
    "lausanne": {"lat": 46.5197, "lon": 6.6323, "country": "switzerland", "region": "western_europe"},
    "lucerne": {"lat": 47.0502, "lon": 8.3093, "country": "switzerland", "region": "western_europe"},
    "luzern": {"lat": 47.0502, "lon": 8.3093, "country": "switzerland", "region": "western_europe"},
    
    # Major Asian cities for better coverage
    "fukuoka": {"lat": 33.5904, "lon": 130.4017, "country": "japan", "region": "east_asia"},
    "sendai": {"lat": 38.2682, "lon": 140.8694, "country": "japan", "region": "east_asia"},
    "busan": {"lat": 35.1796, "lon": 129.0756, "country": "south korea", "region": "east_asia"},
    "incheon": {"lat": 37.4563, "lon": 126.7052, "country": "south korea", "region": "east_asia"},
    "daegu": {"lat": 35.8714, "lon": 128.6014, "country": "south korea", "region": "east_asia"},
    "daejeon": {"lat": 36.3504, "lon": 127.3845, "country": "south korea", "region": "east_asia"},
    "gwangju": {"lat": 35.1595, "lon": 126.8526, "country": "south korea", "region": "east_asia"},
    "ulsan": {"lat": 35.5384, "lon": 129.3114, "country": "south korea", "region": "east_asia"},
    "surat": {"lat": 21.1702, "lon": 72.8311, "country": "india", "region": "south_asia"},
    "thane": {"lat": 19.2183, "lon": 72.9781, "country": "india", "region": "south_asia"},
    "bhopal": {"lat": 23.2599, "lon": 77.4126, "country": "india", "region": "south_asia"},
    "visakhapatnam": {"lat": 17.6868, "lon": 83.2185, "country": "india", "region": "south_asia"},
    "patna": {"lat": 25.5941, "lon": 85.1376, "country": "india", "region": "south_asia"},
    "vadodara": {"lat": 22.3072, "lon": 73.1812, "country": "india", "region": "south_asia"},
    "ghaziabad": {"lat": 28.6692, "lon": 77.4538, "country": "india", "region": "south_asia"},
    "ludhiana": {"lat": 30.9010, "lon": 75.8573, "country": "india", "region": "south_asia"},
    "agra": {"lat": 27.1767, "lon": 78.0081, "country": "india", "region": "south_asia"},
    "nashik": {"lat": 19.9975, "lon": 73.7898, "country": "india", "region": "south_asia"},
    "faridabad": {"lat": 28.4089, "lon": 77.3178, "country": "india", "region": "south_asia"},
    "meerut": {"lat": 28.9845, "lon": 77.7064, "country": "india", "region": "south_asia"},
    "rajkot": {"lat": 22.3039, "lon": 70.8022, "country": "india", "region": "south_asia"},
    "kalyan": {"lat": 19.2437, "lon": 73.1355, "country": "india", "region": "south_asia"},
    "vasai": {"lat": 19.4911, "lon": 72.8054, "country": "india", "region": "south_asia"},
    "varanasi": {"lat": 25.3176, "lon": 82.9739, "country": "india", "region": "south_asia"},
    "amritsar": {"lat": 31.6340, "lon": 74.8723, "country": "india", "region": "south_asia"},
    "aurangabad": {"lat": 19.8762, "lon": 75.3433, "country": "india", "region": "south_asia"},
    
    # Additional African cities
    "addis ababa": {"lat": 9.0320, "lon": 38.7469, "country": "ethiopia", "region": "east_africa"},
    "kigali": {"lat": -1.9441, "lon": 30.0619, "country": "rwanda", "region": "east_africa"},
    "kinshasa": {"lat": -4.4419, "lon": 15.2663, "country": "democratic republic of congo", "region": "central_africa"},
    "lubumbashi": {"lat": -11.6604, "lon": 27.4794, "country": "democratic republic of congo", "region": "central_africa"},
    "brazzaville": {"lat": -4.2634, "lon": 15.2429, "country": "congo", "region": "central_africa"},
    "abidjan": {"lat": 5.3600, "lon": -4.0083, "country": "ivory coast", "region": "west_africa"},
    "yamoussoukro": {"lat": 6.8276, "lon": -5.2893, "country": "ivory coast", "region": "west_africa"},
    "accra": {"lat": 5.6037, "lon": -0.1870, "country": "ghana", "region": "west_africa"},
    "kumasi": {"lat": 6.6884, "lon": -1.6244, "country": "ghana", "region": "west_africa"},
    "dakar": {"lat": 14.7167, "lon": -17.4677, "country": "senegal", "region": "west_africa"},
    "bamako": {"lat": 12.6392, "lon": -8.0029, "country": "mali", "region": "west_africa"},
    "ouagadougou": {"lat": 12.3714, "lon": -1.5197, "country": "burkina faso", "region": "west_africa"},
    "tunis": {"lat": 36.8065, "lon": 10.1815, "country": "tunisia", "region": "north_africa"},
    "sfax": {"lat": 34.7405, "lon": 10.7603, "country": "tunisia", "region": "north_africa"},
    "tripoli": {"lat": 32.8872, "lon": 13.1913, "country": "libya", "region": "north_africa"},
    "benghazi": {"lat": 32.1165, "lon": 20.0686, "country": "libya", "region": "north_africa"},
    "rabat": {"lat": 34.0209, "lon": -6.8416, "country": "morocco", "region": "north_africa"},
    "fez": {"lat": 34.0331, "lon": -5.0003, "country": "morocco", "region": "north_africa"},
    "marrakech": {"lat": 31.6295, "lon": -7.9811, "country": "morocco", "region": "north_africa"},
    "marrakesh": {"lat": 31.6295, "lon": -7.9811, "country": "morocco", "region": "north_africa"},
    "tangier": {"lat": 35.7595, "lon": -5.8340, "country": "morocco", "region": "north_africa"},
    "tanger": {"lat": 35.7595, "lon": -5.8340, "country": "morocco", "region": "north_africa"}
}

def expand_location_keywords():
    """Safely add new cities to location_keywords.json"""
    
    # Load existing data
    keywords_path = "config/location_keywords.json"
    
    if not os.path.exists(keywords_path):
        print(f"❌ {keywords_path} not found")
        return False
    
    try:
        with open(keywords_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load {keywords_path}: {e}")
        return False
    
    if 'cities' not in data:
        print(f"❌ No 'cities' section in {keywords_path}")
        return False
    
    # Track additions
    existing_cities = set(data['cities'].keys())
    added_cities = []
    skipped_cities = []
    
    # Add new cities that don't already exist
    for city_name, city_data in NEW_CITIES.items():
        city_key = city_name.lower().strip()
        
        if city_key in existing_cities:
            skipped_cities.append(city_name)
            continue
            
        data['cities'][city_key] = city_data
        added_cities.append(city_name)
    
    # Write back the updated data
    try:
        with open(keywords_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"❌ Failed to write {keywords_path}: {e}")
        return False
    
    # Report results
    print(f"✅ Location keywords expansion complete!")
    print(f"📊 Added {len(added_cities)} new cities")
    print(f"📊 Skipped {len(skipped_cities)} existing cities")
    print(f"📊 Total cities now: {len(data['cities'])}")
    
    if added_cities:
        print("\n🆕 Added cities:")
        for city in sorted(added_cities)[:20]:  # Show first 20
            print(f"   • {city}")
        if len(added_cities) > 20:
            print(f"   ... and {len(added_cities) - 20} more")
    
    if skipped_cities:
        print(f"\n⚠️  Skipped {len(skipped_cities)} existing cities (no duplicates created)")
    
    return True

if __name__ == "__main__":
    success = expand_location_keywords()
    exit(0 if success else 1)
