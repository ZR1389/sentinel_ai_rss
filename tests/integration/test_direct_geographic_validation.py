#!/usr/bin/env python3
"""
Direct test of geographic validation logic without LLM dependencies
"""

import sys
import os

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
        "confidence": 0.76,
    }
    
    confidence_score, warning_type, warning_msg = _validate_location_match("Cairo", alert_location_data)
    
    print(f"Query: Cairo, Alert data: Budapest, Hungary")
    print(f"Confidence score: {confidence_score}")
    print(f"Warning type: {warning_type}")
    print(f"Warning: {warning_msg}")
    
    # Assertions
    assert confidence_score <= 15, f"Confidence should be capped at 15, got {confidence_score}"
    assert warning_type == "geographic_mismatch", f"Warning type should be geographic_mismatch, got {warning_type}"
    assert "Location data mismatch" in warning_msg, "Warning message should indicate mismatch"
    
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

def test_geographic_distance():
    """Test geographic distance calculation"""
    print("\nTesting geographic distance...")
    
    from advisor import _calculate_geographic_distance
    
    # Cairo: 30.0444, 31.2357
    # Budapest: 47.4979, 19.0402
    # Distance should be ~1400km
    
    distance = _calculate_geographic_distance(30.0444, 31.2357, 47.4979, 19.0402)
    print(f"Distance Cairo to Budapest: {distance:.0f} km")
    
    assert 1300 <= distance <= 1500, f"Distance should be ~1400km, got {distance:.0f}km"
    
    print("✓ Geographic distance test passed")

def run_all_tests():
    """Run all validation tests"""
    print("=== Direct Geographic Validation Tests ===\n")
    
    try:
        test_geographic_validation_logic()
    except Exception as e:
        print(f"✗ Geographic validation logic test failed: {e}")
        return False
    
    try:
        test_location_coordinates()
    except Exception as e:
        print(f"✗ Location coordinates test failed: {e}")
        return False
    
    try:
        test_geographic_distance()
    except Exception as e:
        print(f"✗ Geographic distance test failed: {e}")
        return False
    
    print("\n✅ All geographic validation tests passed!")
    return True

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
