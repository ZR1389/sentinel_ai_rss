#!/usr/bin/env python3
"""
Test the new Geographic Validation Function in advisor.py
Tests the Budapest->Cairo scenario to see if it improves location matching
"""

import os
import sys
import json

# Add current directory to path to import advisor
sys.path.insert(0, '/Users/zikarakita/Documents/sentinel_ai_rss')

try:
    from advisor import _validate_location_match, generate_advice
except ImportError as e:
    print(f"Failed to import advisor: {e}")
    sys.exit(1)

def test_geographic_validation():
    """Test the _validate_location_match function directly"""
    print("=" * 60)
    print("TESTING GEOGRAPHIC VALIDATION FUNCTION")
    print("=" * 60)
    
    # Test Case 1: Perfect Match (Budapest query, Budapest data)
    print("\nTest 1: Perfect City Match")
    query_location = "Budapest"
    alert_location_data = {"city": "Budapest", "country": "Hungary", "region": "Central Europe"}
    match_score, matched_name, warning = _validate_location_match(query_location, alert_location_data)
    print(f"Query: '{query_location}' vs Alert: {alert_location_data}")
    print(f"Result: Score={match_score}, Name='{matched_name}', Warning='{warning}'")
    
    # Test Case 2: Severe Mismatch (Budapest query, Cairo data)
    print("\nTest 2: Severe Geographic Mismatch")
    query_location = "Budapest"
    alert_location_data = {"city": "Cairo", "country": "Egypt", "region": "Middle East"}
    match_score, matched_name, warning = _validate_location_match(query_location, alert_location_data)
    print(f"Query: '{query_location}' vs Alert: {alert_location_data}")
    print(f"Result: Score={match_score}, Name='{matched_name}', Warning='{warning}'")
    
    # Test Case 3: Region Match (Budapest query, Europe data)
    print("\nTest 3: Region Match")
    query_location = "Budapest"
    alert_location_data = {"city": "", "country": "Hungary", "region": "Europe"}
    match_score, matched_name, warning = _validate_location_match(query_location, alert_location_data)
    print(f"Query: '{query_location}' vs Alert: {alert_location_data}")
    print(f"Result: Score={match_score}, Name='{matched_name}', Warning='{warning}'")
    
    # Test Case 4: Country Match (Budapest query, Hungary data)
    print("\nTest 4: Country Match")
    query_location = "Budapest"
    alert_location_data = {"city": "", "country": "Hungary", "region": ""}
    match_score, matched_name, warning = _validate_location_match(query_location, alert_location_data)
    print(f"Query: '{query_location}' vs Alert: {alert_location_data}")
    print(f"Result: Score={match_score}, Name='{matched_name}', Warning='{warning}'")
    
    return True

def test_advisor_with_geographic_validation():
    """Test the full advisor with geographic validation scenarios"""
    print("\n" + "=" * 60)
    print("TESTING ADVISOR WITH GEOGRAPHIC VALIDATION")
    print("=" * 60)
    
    # Create test alerts with different locations
    budapest_alert = {
        "title": "Security Alert: Increased Crime in Budapest City Center",
        "summary": "Reports of pickpocketing and theft incidents near tourist areas",
        "city": "Budapest",
        "country": "Hungary", 
        "region": "Central Europe",
        "category": "Crime",
        "subcategory": "Theft",
        "label": "Medium Risk",
        "score": 75.5,
        "confidence": 0.8,
        "domains": ["physical_safety", "travel_mobility"],
        "sources": [{"name": "Hungarian Police", "link": "https://police.hu"}],
        "trend_direction": "increasing",
        "incident_count_30d": 15,
        "anomaly_flag": True,
        "future_risk_probability": 0.6
    }
    
    cairo_alert = {
        "title": "Security Alert: Political Unrest in Cairo",
        "summary": "Protests and civil unrest reported in downtown Cairo",
        "city": "Cairo",
        "country": "Egypt",
        "region": "Middle East",
        "category": "Civil Unrest",
        "subcategory": "Protests",
        "label": "High Risk",
        "score": 85.0,
        "confidence": 0.9,
        "domains": ["civil_unrest", "travel_mobility"],
        "sources": [{"name": "Egyptian Ministry", "link": "https://egypt.gov.eg"}],
        "trend_direction": "increasing",
        "incident_count_30d": 8,
        "anomaly_flag": True,
        "future_risk_probability": 0.75
    }
    
    # Test 1: Query about Budapest with Budapest alert (should match well)
    print("\nTest 1: Budapest Query with Budapest Alert (Good Match)")
    query1 = "I'm traveling to Budapest next week. What security risks should I be aware of?"
    profile1 = {"location": "Budapest", "role": "traveler"}
    
    result1 = generate_advice(query1, [budapest_alert], user_profile=profile1)
    advisory1 = result1.get("reply", "")
    
    print(f"Query: {query1}")
    print(f"Alert Location: {budapest_alert['city']}, {budapest_alert['country']}")
    print("Advisory contains geographic warning:", "WARNING:" in advisory1 and "does not match" in advisory1)
    print("Advisory length:", len(advisory1), "characters")
    print("Advisory preview:", advisory1[:200] + "..." if len(advisory1) > 200 else advisory1)
    
    # Test 2: Query about Budapest with Cairo alert (should trigger warning)
    print("\n" + "-" * 40)
    print("Test 2: Budapest Query with Cairo Alert (Mismatch)")
    query2 = "I'm traveling to Budapest next week. What security risks should I be aware of?"
    profile2 = {"location": "Budapest", "role": "traveler"}
    
    result2 = generate_advice(query2, [cairo_alert], user_profile=profile2)
    advisory2 = result2.get("reply", "")
    
    print(f"Query: {query2}")
    print(f"Alert Location: {cairo_alert['city']}, {cairo_alert['country']}")
    print("Advisory contains geographic warning:", "WARNING:" in advisory2 and "does not match" in advisory2)
    print("Advisory length:", len(advisory2), "characters")
    print("Advisory preview:", advisory2[:200] + "..." if len(advisory2) > 200 else advisory2)
    
    # Compare results
    print("\n" + "=" * 40)
    print("COMPARISON:")
    print("=" * 40)
    print(f"Good Match (Budapest->Budapest): Warning present = {('WARNING:' in advisory1 and 'does not match' in advisory1)}")
    print(f"Bad Match (Budapest->Cairo): Warning present = {('WARNING:' in advisory2 and 'does not match' in advisory2)}")
    
    improvement = ("WARNING:" in advisory2 and "does not match" in advisory2) and not ("WARNING:" in advisory1 and "does not match" in advisory1)
    print(f"Geographic Validation Working Correctly: {improvement}")
    
    return improvement

def main():
    """Run all tests"""
    print("TESTING GEOGRAPHIC VALIDATION IMPROVEMENTS")
    print("=" * 60)
    
    try:
        # Test the validation function directly
        test_geographic_validation()
        
        # Test the full advisor integration
        improvement = test_advisor_with_geographic_validation()
        
        print("\n" + "=" * 60)
        print("FINAL RESULT")
        print("=" * 60)
        
        if improvement:
            print("✅ SUCCESS: Geographic validation is working!")
            print("   - Correctly identifies location mismatches")
            print("   - Adds appropriate warnings for geographic inconsistencies")
            print("   - Should prevent Budapest->Cairo confusion")
            return 0
        else:
            print("❌ ISSUE: Geographic validation may not be fully integrated")
            print("   - Function exists but may not be called in advisor flow")
            print("   - Need to integrate validation into advisory generation")
            return 1
            
    except Exception as e:
        print(f"❌ ERROR: Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
