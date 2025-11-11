#!/usr/bin/env python3
"""
Test script to verify geographic validation and recent changes

This script tests:
1. Geographic validation in advisor.py
2. Connection pooling functionality
3. Location keywords loading
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_budapest_to_cairo_mismatch():
    """Test geographic validation with location mismatch"""
    from advisor import generate_advice
    
    alerts = [{
        "city": "Budapest",
        "country": "Hungary",
        "confidence": 0.76,
        "incident_count_30d": 1,
        "trend_direction": "decreasing",
        "baseline_ratio": 1.0,
        "domains": ["travel_mobility"]
    }]
    
    result = generate_advice("Cairo", alerts)
    
    # Must contain warning
    assert "⚠️ WARNING: Location data mismatch" in result
    # Confidence must be capped
    assert "Confidence — 15" in result or "Confidence — 12" in result
    # No specific venues
    assert "pharmacy" not in result.lower() or "generic" in result.lower()
    # Has data provenance
    assert "DATA PROVENANCE" in result

def test_connection_pool():
    """Test connection pooling functionality"""
    from db_utils import get_connection_pool
    pool = get_connection_pool()
    assert pool.minconn == 1
    assert pool.maxconn == 20

def test_location_keywords_loading():
    """Test that location keywords are properly loaded"""
    from city_utils import _CITY_COORDS_CACHE
    assert "cairo" in _CITY_COORDS_CACHE
    assert _CITY_COORDS_CACHE["cairo"] == (30.0444, 31.2357)

def run_tests():
    """Run all tests manually"""
    print("=== Geographic Validation and Changes Test ===\n")
    
    try:
        print("1. Testing Budapest to Cairo mismatch...")
        test_budapest_to_cairo_mismatch()
        print("✓ Geographic validation test passed")
    except Exception as e:
        print(f"✗ Geographic validation test failed: {e}")
    
    try:
        print("\n2. Testing connection pool...")
        test_connection_pool()
        print("✓ Connection pool test passed")
    except Exception as e:
        print(f"✗ Connection pool test failed: {e}")
    
    try:
        print("\n3. Testing location keywords loading...")
        test_location_keywords_loading()
        print("✓ Location keywords test passed")
    except Exception as e:
        print(f"✗ Location keywords test failed: {e}")
    
    print("\n=== All Tests Complete ===")

if __name__ == "__main__":
    run_tests()
