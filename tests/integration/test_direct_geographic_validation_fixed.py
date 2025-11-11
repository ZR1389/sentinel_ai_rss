#!/usr/bin/env python3
"""
Direct test of geographic validation logic without LLM dependencies
"""

import sys
import os
import math

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_geographic_validation_logic():
    """Test the geographic validation logic directly"""
    print("Testing geographic validation logic...")
    
    # Import the validation function directly
    from advisor import _validate_location_match
    
    # Test case: Budapest data for Cairo query (should trigger warning)
    alert_location_data = {
        "city": "Budapest",
        "country": "Hungary", 
    }
    
    match_score, matched_name, warning = _validate_location_match("Cairo", alert_location_data)
    
    print(f"Query: Cairo, Alert data: Budapest, Hungary")
    print(f"Match score: {match_score}")
    print(f"Matched name: {matched_name}")
    print(f"Warning: {warning}")
    
    # Assertions
    assert match_score < 30, f"Match score should be low (<30), got {match_score}"
    assert "Budapest" in matched_name, f"Matched name should contain Budapest, got '{matched_name}'"
    assert "WARNING" in warning, "Warning message should contain WARNING"
    assert "does not match" in warning, "Warning should indicate mismatch"
    
    print("✓ Geographic validation logic test passed")

def test_location_coordinates():
    """Test specific location coordinates"""
    print("\nTesting location coordinates...")
    
    from city_utils import get_city_coords, get_country_for_city
    
    # Test Cairo coordinates
    lat, lon = get_city_coords("cairo")
    country = get_country_for_city("cairo")
    
    print(f"Cairo: {lat}, {lon} in {country}")
    
    assert lat == 30.0444, f"Cairo latitude should be 30.0444, got {lat}"
    assert lon == 31.2357, f"Cairo longitude should be 31.2357, got {lon}"
    assert country == "egypt", f"Cairo country should be 'egypt', got '{country}'"
    
    # Test Budapest coordinates  
    lat, lon = get_city_coords("budapest")
    country = get_country_for_city("budapest")
    
    print(f"Budapest: {lat}, {lon} in {country}")
    
    assert lat == 47.4979, f"Budapest latitude should be 47.4979, got {lat}"
    assert lon == 19.0402, f"Budapest longitude should be 19.0402, got {lon}"
    assert country == "hungary", f"Budapest country should be 'hungary', got '{country}'"
    
    print("✓ Location coordinates test passed")

def test_geographic_coordinates_available():
    """Test geographic coordinates are available for distance calculations"""
    print("\nTesting geographic coordinates availability...")
    
    from city_utils import get_city_coords
    
    # Test that we can get coordinates for Cairo and Budapest
    cairo_lat, cairo_lon = get_city_coords("cairo")
    budapest_lat, budapest_lon = get_city_coords("budapest")
    
    print(f"Cairo coordinates: {cairo_lat}, {cairo_lon}")
    print(f"Budapest coordinates: {budapest_lat}, {budapest_lon}")
    
    assert cairo_lat is not None and cairo_lon is not None, "Cairo coordinates should be available"
    assert budapest_lat is not None and budapest_lon is not None, "Budapest coordinates should be available"
    
    # Calculate simple distance (not testing accuracy, just availability)
    if all([cairo_lat, cairo_lon, budapest_lat, budapest_lon]):
        # Haversine formula for distance calculation
        R = 6371  # Earth's radius in km
        dlat = math.radians(budapest_lat - cairo_lat)
        dlon = math.radians(budapest_lon - cairo_lon)
        a = (math.sin(dlat/2) * math.sin(dlat/2) + 
             math.cos(math.radians(cairo_lat)) * math.cos(math.radians(budapest_lat)) * 
             math.sin(dlon/2) * math.sin(dlon/2))
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = R * c
        
        print(f"Calculated distance: {distance:.0f} km")
        assert 2000 <= distance <= 2300, f"Distance should be reasonable (~2200km), got {distance:.0f}km"
    
    print("✓ Geographic coordinates availability test passed")

def test_connection_pool():
    """Test connection pooling functionality"""
    print("\nTesting connection pool...")
    
    from db_utils import get_connection_pool
    pool = get_connection_pool()
    
    print(f"Pool min connections: {pool.minconn}")
    print(f"Pool max connections: {pool.maxconn}")
    
    assert pool.minconn == 1, f"Min connections should be 1, got {pool.minconn}"
    assert pool.maxconn == 20, f"Max connections should be 20, got {pool.maxconn}"
    
    print("✓ Connection pool test passed")

def run_all_tests():
    """Run all validation tests"""
    print("=== Direct Geographic Validation Tests ===\n")
    
    tests = [
        ("Geographic validation logic", test_geographic_validation_logic),
        ("Location coordinates", test_location_coordinates),
        ("Geographic coordinates availability", test_geographic_coordinates_available),
        ("Connection pool", test_connection_pool)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"✗ {test_name} test failed: {e}")
            failed += 1
    
    print(f"\n=== Test Results ===")
    print(f"✓ Passed: {passed}")
    print(f"✗ Failed: {failed}")
    
    if failed == 0:
        print("🎉 All geographic validation tests passed!")
        return True
    else:
        print("❌ Some tests failed!")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
