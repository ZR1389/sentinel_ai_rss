#!/usr/bin/env python3
"""
Test script to verify city_utils.py integration with new location_keywords.json structure

This script tests:
1. Proper coordinate loading from the new JSON structure
2. City-to-country mapping functionality
3. Edge case handling for location data
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import city_utils
import json

def test_coordinate_loading():
    """Test that coordinates are properly loaded from the new JSON structure"""
    print("Testing coordinate loading...")
    
    # Test some known cities
    test_cities = ["new york", "london", "paris", "tokyo"]
    
    for city in test_cities:
        lat, lon = city_utils.get_city_coords(city)
        if lat is not None and lon is not None:
            print(f"✓ {city.title()}: {lat}, {lon}")
        else:
            print(f"✗ {city.title()}: No coordinates found")

def test_city_to_country_mapping():
    """Test the city-to-country mapping functionality"""
    print("\nTesting city-to-country mapping...")
    
    test_cities = ["new york", "london", "paris", "tokyo", "toronto", "sydney"]
    
    for city in test_cities:
        country = city_utils.get_country_for_city(city)
        if country:
            print(f"✓ {city.title()} -> {country}")
        else:
            print(f"✗ {city.title()}: No country mapping found")

def test_cache_stats():
    """Test the cache statistics functionality"""
    print("\nTesting cache statistics...")
    
    stats = city_utils.get_city_utils_stats()
    print(f"Cities loaded: {stats['cities_loaded']}")
    print(f"Countries loaded: {stats['countries_loaded']}")
    print(f"City-country mappings: {stats['city_country_mappings']}")

def test_normalization():
    """Test city and country normalization"""
    print("\nTesting normalization...")
    
    test_cases = [
        ("new york", "usa"),
        ("LONDON", "UK"),
        ("paris", None),
        ("invalid_city", "unknown_country")
    ]
    
    for city, country in test_cases:
        norm_city, norm_country = city_utils.normalize_city_country(city, country)
        print(f"{city}, {country} -> {norm_city}, {norm_country}")

def test_fuzzy_matching():
    """Test fuzzy city matching"""
    print("\nTesting fuzzy matching...")
    
    test_texts = [
        "Breaking news from New York today",
        "Incident reported in London area",
        "Nothing happening in randomville",
        "Paris situation developing"
    ]
    
    for text in test_texts:
        match = city_utils.fuzzy_match_city(text)
        print(f"'{text}' -> {match}")

def test_edge_cases():
    """Test edge cases and error handling"""
    print("\nTesting edge cases...")
    
    # Test empty inputs
    lat, lon = city_utils.get_city_coords("")
    print(f"Empty city: {lat}, {lon}")
    
    country = city_utils.get_country_for_city("")
    print(f"Empty city country: {country}")
    
    # Test None inputs
    lat, lon = city_utils.get_city_coords(None)
    print(f"None city: {lat}, {lon}")
    
    # Test case sensitivity
    lat1, lon1 = city_utils.get_city_coords("London")
    lat2, lon2 = city_utils.get_city_coords("london")
    lat3, lon3 = city_utils.get_city_coords("LONDON")
    
    print(f"Case sensitivity test:")
    print(f"  London: {lat1}, {lon1}")
    print(f"  london: {lat2}, {lon2}")
    print(f"  LONDON: {lat3}, {lon3}")

def main():
    """Run all tests"""
    print("=== City Utils Integration Tests ===\n")
    
    test_coordinate_loading()
    test_city_to_country_mapping()
    test_cache_stats()
    test_normalization()
    test_fuzzy_matching()
    test_edge_cases()
    
    print("\n=== Integration Tests Complete ===")

if __name__ == "__main__":
    main()
