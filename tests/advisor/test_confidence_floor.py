#!/usr/bin/env python3
"""Test confidence floor in fallback advisory"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from advisor import _fallback_advisory

def test_confidence_floor():
    """Test that confidence is properly floored based on location and data quality"""
    
    print("=== Testing Confidence Floor in Fallback Advisory ===\n")
    
    # Base alert data
    base_alert = {
        "confidence": 0.8,  # 80% original confidence
        "category": "cyber_it",
        "subcategory": "Ransomware",
        "trend_direction": "increasing",
        "baseline_ratio": 2.5,
        "incident_count_30d": 10,
        "anomaly_flag": True
    }
    
    base_input_data = {
        "region": "Test Region",
        "category": "Cyber Security",
        "domains": ["cyber_it"],
        "sources": [{"name": "TestSource", "link": "http://example.com"}],
        "reports_analyzed": 5,
        "role_actions": {"it_secops": ["Test action 1", "Test action 2"]},
        "next_review_hours": "6h"
    }
    
    trend_line = "Because trend_direction=increasing for cyber risk, do enforce passkeys/MFA."
    
    # Test Case 1: Good location match + valid data (no penalties)
    print("--- Test 1: Good Location Match + Valid Data ---")
    input_data_1 = {
        **base_input_data,
        "location_match_score": 85,  # Good match
        "data_statistically_valid": True
    }
    
    advisory_1 = _fallback_advisory(base_alert, trend_line, input_data_1)
    confidence_line_1 = [line for line in advisory_1.split('\n') if line.startswith('CONFIDENCE — ')][0]
    print(f"Original confidence: 80%")
    print(f"Result: {confidence_line_1}")
    print("Expected: No penalties applied, ~80%")
    
    # Test Case 2: Severe location mismatch (< 30)
    print("\n--- Test 2: Severe Location Mismatch ---")
    input_data_2 = {
        **base_input_data,
        "location_match_score": 15,  # Severe mismatch 
        "data_statistically_valid": True
    }
    
    advisory_2 = _fallback_advisory(base_alert, trend_line, input_data_2)
    confidence_line_2 = [line for line in advisory_2.split('\n') if line.startswith('CONFIDENCE — ')][0]
    print(f"Original confidence: 80%")
    print(f"Result: {confidence_line_2}")
    print("Expected: Capped at 15% due to location mismatch")
    
    # Test Case 3: Invalid data (insufficient incidents)
    print("\n--- Test 3: Insufficient Data ---")
    input_data_3 = {
        **base_input_data,
        "location_match_score": 90,  # Good match
        "data_statistically_valid": False  # Insufficient data
    }
    
    advisory_3 = _fallback_advisory(base_alert, trend_line, input_data_3)
    confidence_line_3 = [line for line in advisory_3.split('\n') if line.startswith('CONFIDENCE — ')][0]
    print(f"Original confidence: 80%")
    print(f"Result: {confidence_line_3}")
    print("Expected: Capped at 25% due to insufficient data")
    
    # Test Case 4: Both penalties (worst case)
    print("\n--- Test 4: Both Location Mismatch + Insufficient Data ---")
    input_data_4 = {
        **base_input_data,
        "location_match_score": 10,  # Severe mismatch
        "data_statistically_valid": False  # Insufficient data
    }
    
    advisory_4 = _fallback_advisory(base_alert, trend_line, input_data_4)
    confidence_line_4 = [line for line in advisory_4.split('\n') if line.startswith('CONFIDENCE — ')][0]
    print(f"Original confidence: 80%")
    print(f"Result: {confidence_line_4}")
    print("Expected: Capped at 15% (lowest of location/data penalties)")
    
    # Test Case 5: Check explanation warnings
    print("\n--- Test 5: Explanation Section Warnings ---")
    explanation_section = advisory_4.split('EXPLANATION —')[1].split('ANALYST CTA —')[0].strip()
    print("Explanation section with warnings:")
    print(explanation_section)
    print("\nExpected warnings:")
    print("- Low location match score warning")
    print("- Insufficient incident data warning")
    
    # Verify warnings are present
    has_location_warning = "Low location match score" in explanation_section
    has_data_warning = "Insufficient incident data" in explanation_section
    
    print(f"\n✅ Location warning present: {has_location_warning}")
    print(f"✅ Data warning present: {has_data_warning}")
    
    if has_location_warning and has_data_warning:
        print("\n🎉 All confidence floor tests passed!")
        print("✅ Confidence is properly capped based on location and data quality")
        print("✅ Warnings are added to explanation section")
    else:
        print("\n❌ Some tests failed - warnings missing")
    
    return has_location_warning and has_data_warning

if __name__ == "__main__":
    success = test_confidence_floor()
    if success:
        print("\n🚀 Confidence floor implementation is working correctly!")
    else:
        print("\n⚠️  Issues detected with confidence floor implementation")
