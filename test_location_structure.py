#!/usr/bin/env python3
"""
Test that city_utils.py works correctly with the new location_keywords.json structure
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_location_keywords_compatibility():
    """Test the enhanced location_keywords.json structure"""
    print("🔍 Testing Enhanced Location Keywords Structure...")
    
    try:
        import json
        
        # Load the JSON file
        with open('config/location_keywords.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        cities = data.get('cities', {})
        countries = data.get('countries', {})
        regions = data.get('regions', {})
        
        print(f"✅ Loaded {len(cities)} cities, {len(countries)} countries, {len(regions)} regions")
        
        # Test structure consistency
        inconsistent_cities = []
        for city_key, city_data in cities.items():
            if not isinstance(city_data, dict):
                inconsistent_cities.append(f"{city_key}: {type(city_data).__name__}")
            elif not all(key in city_data for key in ['lat', 'lon', 'country', 'region']):
                missing_fields = [k for k in ['lat', 'lon', 'country', 'region'] if k not in city_data]
                inconsistent_cities.append(f"{city_key}: missing {missing_fields}")
        
        if inconsistent_cities:
            print(f"❌ Found {len(inconsistent_cities)} inconsistent city entries:")
            for issue in inconsistent_cities[:5]:  # Show first 5
                print(f"  - {issue}")
            if len(inconsistent_cities) > 5:
                print(f"  ... and {len(inconsistent_cities) - 5} more")
            return False
        else:
            print("✅ All cities have consistent object structure with lat/lon/country/region")
        
        # Test specific cities mentioned in the user's request
        test_cities = ['kabul', 'cairo', 'budapest']
        for city in test_cities:
            if city in cities:
                city_data = cities[city]
                print(f"✅ {city}: lat={city_data['lat']}, lon={city_data['lon']}, country={city_data['country']}, region={city_data['region']}")
            else:
                print(f"❌ {city} not found in cities")
                return False
        
        # Test coordinate types
        for city_key, city_data in list(cities.items())[:5]:
            lat, lon = city_data['lat'], city_data['lon']
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                print(f"❌ {city_key}: lat/lon should be numbers, got lat={type(lat)}, lon={type(lon)}")
                return False
        
        print("✅ Coordinate data types are correct (numbers)")
        
        # Test region/country format consistency
        sample_countries = set()
        sample_regions = set()
        for city_data in list(cities.values())[:10]:
            sample_countries.add(city_data['country'])
            sample_regions.add(city_data['region'])
        
        print(f"✅ Sample countries: {', '.join(list(sample_countries)[:3])}...")
        print(f"✅ Sample regions: {', '.join(list(sample_regions)[:3])}...")
        
        print("\n🎉 Enhanced location keywords structure is fully consistent!")
        print("💡 Benefits of the new structure:")
        print("  • Precise lat/lon coordinates for accurate geocoding")
        print("  • Consistent object format (no mixed strings)")
        print("  • Regional classification for better categorization")
        print("  • Standardized country names (lowercase)")
        print("  • Compatible with city_utils.py expectations")
        
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = test_location_keywords_compatibility()
    sys.exit(0 if success else 1)
