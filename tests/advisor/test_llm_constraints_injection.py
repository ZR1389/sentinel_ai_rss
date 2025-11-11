#!/usr/bin/env python3
"""
Test the enhanced LLM constraints injection for location rules enforcement
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from advisor import render_advisory

def test_llm_constraints_injection():
    """Test that LLM constraints are properly injected based on location validation"""
    
    print("=== Testing LLM Constraints Injection for Location Rules ===\n")
    
    # Test case 1: Poor location match (should enforce generic recommendations)
    print("--- Test 1: Poor Location Match (Budapest query + Cairo data) ---")
    
    budapest_alert = {
        "title": "Security Alert in Cairo",
        "summary": "Increased security measures in downtown Cairo",
        "city": "Cairo",
        "country": "Egypt", 
        "region": "Middle East",
        "category": "civil_unrest",
        "confidence": 0.8,
        "incident_count_30d": 5,
        "trend_direction": "increasing",
        "baseline_ratio": 1.5,
        "sources": [{"name": "Local News", "link": "http://example.com"}]
    }
    
    budapest_profile = {"location": "Budapest"}
    
    try:
        advisory = render_advisory(
            budapest_alert, 
            "I'm traveling to Budapest for business. What should I know?",
            budapest_profile
        )
        
        print(f"✅ Advisory generated ({len(advisory)} chars)")
        
        # Check if geographic warning is present
        if "WARNING: Input data location" in advisory:
            print("✅ Geographic validation warning present")
        else:
            print("❌ Geographic validation warning missing")
            
        # Check if provenance section exists
        if "DATA PROVENANCE" in advisory:
            print("✅ Data provenance section present")
        else:
            print("❌ Data provenance section missing")
            
        print()
        
    except Exception as e:
        print(f"❌ Error generating advisory: {e}")
        print()
    
    # Test case 2: Good location match (should allow specific recommendations)
    print("--- Test 2: Good Location Match (Paris query + Paris data) ---")
    
    paris_alert = {
        "title": "Security Alert in Paris",
        "summary": "Increased pickpocketing in tourist areas",
        "city": "Paris",
        "country": "France",
        "region": "Île-de-France", 
        "category": "physical_safety",
        "confidence": 0.9,
        "incident_count_30d": 15,
        "trend_direction": "stable",
        "baseline_ratio": 1.1,
        "sources": [{"name": "Prefecture Police", "link": "http://example.com"}]
    }
    
    paris_profile = {"location": "Paris"}
    
    try:
        advisory = render_advisory(
            paris_alert,
            "I'm visiting Paris next week. Any security advice?", 
            paris_profile
        )
        
        print(f"✅ Advisory generated ({len(advisory)} chars)")
        
        # Check if no geographic warning (good match)
        if "WARNING: Input data location" not in advisory:
            print("✅ No geographic validation warning (good match)")
        else:
            print("❌ Unexpected geographic validation warning present")
            
        print()
        
    except Exception as e:
        print(f"❌ Error generating advisory: {e}")
        print()

def test_constraints_data_structure():
    """Test that the llm_constraints are properly structured in input_data"""
    
    print("=== Testing llm_constraints Data Structure ===\n")
    
    # We'll test this by examining the _build_input_payload indirectly
    from advisor import _build_input_payload, _validate_location_match
    
    # Test scenario
    alert = {
        "title": "Test Alert",
        "city": "Cairo", 
        "country": "Egypt",
        "region": "Middle East"
    }
    
    user_message = "Budapest travel advice"
    profile_data = {"location": "Budapest"}
    
    try:
        # Get location validation data
        location_match_score, matched_name, warning = _validate_location_match(
            "Budapest", 
            {"city": "Cairo", "country": "Egypt", "region": "Middle East"}
        )
        
        print(f"Location match score: {location_match_score}")
        print(f"Location warning: {warning}")
        print(f"Should enforce generic recommendations: {location_match_score < 30}")
        print()
        
        # Build input payload
        input_data, roles, hits = _build_input_payload(alert, user_message, profile_data)
        
        # Check if location data is present
        if "location_match_score" in input_data:
            print("✅ location_match_score present in input_data")
        else:
            print("❌ location_match_score missing from input_data")
            
        if "location_precision" in input_data:
            print("✅ location_precision present in input_data")
        else:
            print("❌ location_precision missing from input_data")
            
        print(f"Input data keys: {list(input_data.keys())}")
        print()
        
    except Exception as e:
        print(f"❌ Error testing input payload: {e}")
        print()

if __name__ == "__main__":
    print("Testing Enhanced LLM Constraints for Location Rules Enforcement\n")
    
    # First test the constraints data structure
    test_constraints_data_structure()
    
    # Then test the full advisory generation
    # Note: This will use actual LLM calls, so we'll mock it for testing
    print("=== LLM Constraints Integration Test ===")
    print("Note: This test validates the constraint injection logic.")
    print("Full LLM testing would require API calls.\n")
    
    test_llm_constraints_injection()
