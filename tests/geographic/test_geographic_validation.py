#!/usr/bin/env python3
"""
Test script for geographic validation in chat handler
"""

import sys
import os

# Add the project root to sys.path
sys.path.insert(0, '/Users/zikarakita/Documents/sentinel_ai_rss')

from chat_handler import _validate_region

def test_geographic_validation():
    """Test the _validate_region function"""
    print("🧪 Testing Geographic Region Validation")
    print("=" * 50)
    
    # Test valid regions (should pass)
    valid_regions = [
        "New York",
        "Paris, France", 
        "Tokyo",
        "Berlin",
        "Mumbai",
        "Sydney, Australia",
        "Cairo",
        "Brazil"
    ]
    
    print("\n✅ Testing Valid Regions:")
    for region in valid_regions:
        result = _validate_region(region)
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {region}: {status}")
    
    # Test invalid/vague regions (should be rejected)
    vague_regions = [
        "europe",
        "ASIA", 
        "Middle East",
        "world",
        "global",
        "africa",
        "Americas",
        "North America",
        "southeast asia",
        "",
        None
    ]
    
    print("\n❌ Testing Vague/Invalid Regions (should be rejected):")
    for region in vague_regions:
        result = _validate_region(region)
        expected = False
        status = "✅ CORRECTLY REJECTED" if result == expected else "❌ INCORRECTLY ACCEPTED"
        print(f"  {region}: {status}")
    
    # Test edge cases
    edge_cases = [
        "EU",    # Too short
        "US",    # Too short  
        "UK",    # Too short
        "UAE",   # Just long enough
        "Egypt", # Should pass
    ]
    
    print("\n🔍 Testing Edge Cases:")
    for region in edge_cases:
        result = _validate_region(region)
        status = "✅ ACCEPTED" if result else "❌ REJECTED"
        print(f"  {region}: {status}")
    
    print("\n" + "=" * 50)
    print("✅ Geographic validation test complete!")

if __name__ == "__main__":
    test_geographic_validation()
