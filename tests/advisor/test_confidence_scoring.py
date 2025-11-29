#!/usr/bin/env python3
"""
test_confidence_scoring.py - Comprehensive tests for centralized confidence scoring

This module tests the new compute_confidence function in threat_engine.py
to ensure it works correctly for all confidence types and edge cases.
"""

import sys
import os
import json
from datetime import datetime

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# Import the function we're testing
try:
    from services.threat_engine import compute_confidence
    print("✓ Successfully imported compute_confidence from threat_engine")
except ImportError as e:
    print(f"✗ Failed to import compute_confidence: {e}")
    sys.exit(1)

def test_category_confidence():
    """Test category confidence calculation"""
    print("\n=== Testing Category Confidence ===")
    
    # Test case 1: High confidence with good signals
    alert_high = {
        "category": "Security",
        "kw_match": {
            "rule": "broad+impact+sentence"
        },
        "summary": "A detailed security incident involving multiple systems and affecting operations across the region",
        "domains": ["security", "cyber"]
    }
    
    conf_high = compute_confidence(alert_high, "category")
    print(f"High confidence case: {conf_high:.2f}")
    assert 0.7 <= conf_high <= 1.0, f"Expected high confidence, got {conf_high}"
    
    # Test case 2: Medium confidence
    alert_medium = {
        "category": "Other",
        "kw_match": {
            "rule": "broad+impact"
        },
        "summary": "Short summary",
        "domains": []
    }
    
    conf_medium = compute_confidence(alert_medium, "category")
    print(f"Medium confidence case: {conf_medium:.2f}")
    assert 0.4 <= conf_medium <= 0.8, f"Expected medium confidence, got {conf_medium}"
    
    # Test case 3: Low confidence
    alert_low = {
        "category": "",
        "summary": "Brief",
        "domains": []
    }
    
    conf_low = compute_confidence(alert_low, "category")
    print(f"Low confidence case: {conf_low:.2f}")
    assert 0.2 <= conf_low <= 0.6, f"Expected low confidence, got {conf_low}"
    
    print("✓ All category confidence tests passed")

def test_location_confidence():
    """Test location confidence calculation"""
    print("\n=== Testing Location Confidence ===")
    
    # Test case 1: High confidence with coordinates
    alert_high = {
        "location_confidence": "high",
        "location_method": "ner",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "country": "United States",
        "city": "New York",
        "summary": "Incident in New York city affecting the United States region"
    }
    
    conf_high = compute_confidence(alert_high, "location")
    print(f"High location confidence: {conf_high:.2f}")
    assert 0.8 <= conf_high <= 1.0, f"Expected high confidence, got {conf_high}"
    
    # Test case 2: Medium confidence
    alert_medium = {
        "location_confidence": "medium",
        "location_method": "llm",
        "country": "Germany"
    }
    
    conf_medium = compute_confidence(alert_medium, "location")
    print(f"Medium location confidence: {conf_medium:.2f}")
    assert 0.6 <= conf_medium <= 0.8, f"Expected medium confidence, got {conf_medium}"
    
    # Test case 3: No location
    alert_none = {
        "location_confidence": "none",
        "location_method": "none"
    }
    
    conf_none = compute_confidence(alert_none, "location")
    print(f"No location confidence: {conf_none:.2f}")
    assert 0.1 <= conf_none <= 0.3, f"Expected low confidence, got {conf_none}"
    
    print("✓ All location confidence tests passed")

def test_threat_confidence():
    """Test threat assessment confidence"""
    print("\n=== Testing Threat Confidence ===")
    
    # Test case 1: High threat score
    alert_high_threat = {
        "threat_score": 85,
        "keyword_weight": 0.8,
        "triggers": ["explosion", "terror", "attack", "bomb"],
        "kw_match": {
            "rule": "broad+impact+sentence"
        }
    }
    
    conf_high = compute_confidence(alert_high_threat, "threat")
    print(f"High threat confidence: {conf_high:.2f}")
    assert 0.7 <= conf_high <= 1.0, f"Expected high confidence, got {conf_high}"
    
    # Test case 2: Medium threat score
    alert_medium_threat = {
        "threat_score": 60,
        "keyword_weight": 0.5,
        "triggers": ["incident"],
        "kw_match": {}
    }
    
    conf_medium = compute_confidence(alert_medium_threat, "threat")
    print(f"Medium threat confidence: {conf_medium:.2f}")
    assert 0.5 <= conf_medium <= 0.8, f"Expected medium confidence, got {conf_medium}"
    
    # Test case 3: Low threat score
    alert_low_threat = {
        "threat_score": 20,
        "keyword_weight": 0.2,
        "triggers": [],
        "kw_match": {}
    }
    
    conf_low = compute_confidence(alert_low_threat, "threat")
    print(f"Low threat confidence: {conf_low:.2f}")
    assert 0.4 <= conf_low <= 0.65, f"Expected lower confidence, got {conf_low}"
    
    print("✓ All threat confidence tests passed")

def test_overall_confidence():
    """Test overall confidence calculation"""
    print("\n=== Testing Overall Confidence ===")
    
    # Test case 1: Complete high-quality alert
    complete_alert = {
        "category": "Security",
        "category_confidence": 0.85,
        "location_confidence": "high",
        "location_method": "ner",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "threat_score": 75,
        "keyword_weight": 0.7,
        "triggers": ["attack", "security"],
        "summary": "Detailed security incident with clear location and high threat level",
        "kw_match": {"rule": "broad+impact+sentence"}
    }
    
    conf_complete = compute_confidence(complete_alert, "overall")
    print(f"Complete alert confidence: {conf_complete:.2f}")
    assert 0.7 <= conf_complete <= 1.0, f"Expected high overall confidence, got {conf_complete}"
    
    # Test case 2: Incomplete alert
    incomplete_alert = {
        "category": "",
        "summary": "Brief",
        "threat_score": 30
    }
    
    conf_incomplete = compute_confidence(incomplete_alert, "overall")
    print(f"Incomplete alert confidence: {conf_incomplete:.2f}")
    assert 0.3 <= conf_incomplete <= 0.7, f"Expected lower overall confidence, got {conf_incomplete}"
    
    print("✓ All overall confidence tests passed")

def test_custom_confidence():
    """Test custom confidence calculation"""
    print("\n=== Testing Custom Confidence ===")
    
    # Test with custom modifiers
    alert = {"category": "Security"}
    
    conf_custom = compute_confidence(
        alert, 
        "custom", 
        base=0.6,
        boost_quality=0.1,
        boost_completeness=0.05,
        penalty_uncertainty=0.02
    )
    
    print(f"Custom confidence: {conf_custom:.2f}")
    assert 0.5 <= conf_custom <= 0.9, f"Expected reasonable custom confidence, got {conf_custom}"
    
    print("✓ Custom confidence test passed")

def test_edge_cases():
    """Test edge cases and error handling"""
    print("\n=== Testing Edge Cases ===")
    
    # Test empty alert
    empty_alert = {}
    conf_empty = compute_confidence(empty_alert, "overall")
    print(f"Empty alert confidence: {conf_empty:.2f}")
    assert 0.3 <= conf_empty <= 0.6, f"Expected fallback confidence, got {conf_empty}"
    
    # Test unknown confidence type
    conf_unknown = compute_confidence({}, "unknown_type")
    print(f"Unknown type confidence: {conf_unknown:.2f}")
    assert conf_unknown == 0.5, f"Expected default 0.5, got {conf_unknown}"
    
    # Test with None values
    alert_with_nones = {
        "category": None,
        "location_confidence": None,
        "threat_score": None
    }
    conf_nones = compute_confidence(alert_with_nones, "overall")
    print(f"Alert with None values confidence: {conf_nones:.2f}")
    assert 0.2 <= conf_nones <= 0.6, f"Expected low confidence for None values, got {conf_nones}"
    
    print("✓ All edge case tests passed")

def benchmark_performance():
    """Benchmark confidence calculation performance"""
    print("\n=== Performance Benchmark ===")
    
    import time
    
    # Create a realistic alert
    test_alert = {
        "category": "Security",
        "category_confidence": 0.8,
        "location_confidence": "high",
        "location_method": "ner",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "threat_score": 70,
        "keyword_weight": 0.65,
        "triggers": ["incident", "security", "attack"],
        "summary": "Security incident involving multiple systems in New York",
        "kw_match": {"rule": "broad+impact+sentence"},
        "domains": ["security", "cyber"]
    }
    
    # Benchmark different confidence types
    confidence_types = ["category", "location", "threat", "overall"]
    iterations = 1000
    
    for conf_type in confidence_types:
        start_time = time.time()
        for _ in range(iterations):
            compute_confidence(test_alert, conf_type)
        end_time = time.time()
        
        avg_time = (end_time - start_time) / iterations * 1000  # ms
        print(f"{conf_type} confidence: {avg_time:.3f}ms avg")
    
    print("✓ Performance benchmark completed")

def main():
    """Run all tests"""
    print("Starting Centralized Confidence Scoring Tests")
    print("=" * 50)
    
    try:
        test_category_confidence()
        test_location_confidence()
        test_threat_confidence()
        test_overall_confidence()
        test_custom_confidence()
        test_edge_cases()
        benchmark_performance()
        
        print("\n" + "=" * 50)
        print("🎉 ALL TESTS PASSED! Centralized confidence scoring is working correctly.")
        
        # Test with a comprehensive real-world example
        print("\n=== Real-World Example ===")
        real_alert = {
            "uuid": "test-123",
            "title": "Cyber Attack on Critical Infrastructure",
            "summary": "A sophisticated cyber attack targeted power grid systems in Berlin, Germany, causing widespread outages affecting over 100,000 residents",
            "category": "Cyber",
            "category_confidence": 0.9,
            "location_confidence": "high",
            "location_method": "ner",
            "country": "Germany",
            "city": "Berlin",
            "latitude": 52.5200,
            "longitude": 13.4050,
            "threat_score": 82,
            "keyword_weight": 0.85,
            "triggers": ["cyber", "attack", "infrastructure", "outage"],
            "kw_match": {"rule": "broad+impact+sentence"},
            "domains": ["cyber", "security", "infrastructure"]
        }
        
        overall_conf = compute_confidence(real_alert, "overall")
        category_conf = compute_confidence(real_alert, "category")
        location_conf = compute_confidence(real_alert, "location")
        threat_conf = compute_confidence(real_alert, "threat")
        
        print(f"Real-world alert confidence scores:")
        print(f"  Overall: {overall_conf:.2f}")
        print(f"  Category: {category_conf:.2f}")
        print(f"  Location: {location_conf:.2f}")
        print(f"  Threat: {threat_conf:.2f}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
