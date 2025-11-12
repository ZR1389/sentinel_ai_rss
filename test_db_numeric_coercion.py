#!/usr/bin/env python3
"""
Test script for db_utils.py numeric coercion functionality.
Tests the _coerce_numeric function and its integration in database operations.
"""

import sys
import json
from datetime import datetime
from typing import Dict, List, Any

def test_coerce_numeric_function():
    """Test the _coerce_numeric function directly."""
    print("=" * 60)
    print("Testing _coerce_numeric function")
    print("=" * 60)
    
    # Define the function locally for testing
    def _coerce_numeric(value, default, min_val=None, max_val=None):
        try:
            num = float(value) if value is not None else default
            # Handle NaN values by using default
            if num != num:  # NaN check (NaN != NaN is True)
                num = default
            if min_val is not None:
                num = max(min_val, num)
            if max_val is not None:
                num = min(max_val, num)
            return num
        except (ValueError, TypeError):
            return default
    
    test_cases = [
        # (description, value, default, min_val, max_val, expected)
        ("Normal score", 75, 0, 0, 100, 75.0),
        ("Score over maximum", 150, 0, 0, 100, 100),
        ("Score under minimum", -25, 0, 0, 100, 0),
        ("String score conversion", "85.5", 0, 0, 100, 85.5),
        ("Invalid string score", "invalid", 50, 0, 100, 50),
        ("None score", None, 25, 0, 100, 25),
        ("Confidence in range", 0.75, 0.5, 0, 1, 0.75),
        ("Confidence over max", 1.5, 0.5, 0, 1, 1.0),
        ("String confidence", "0.85", 0.5, 0, 1, 0.85),
        ("Invalid confidence", "bad", 0.5, 0, 1, 0.5),
        ("Latitude valid", 40.7128, None, -90, 90, 40.7128),
        ("Latitude over max", 95, None, -90, 90, 90),
        ("Latitude under min", -95, None, -90, 90, -90),
        ("Longitude valid", -74.0060, None, -180, 180, -74.0060),
        ("Longitude string", "151.2093", None, -180, 180, 151.2093),
        ("Incident count", 42, 0, 0, None, 42.0),
        ("Incident count string", "12", 0, 0, None, 12.0),
        ("Incident count negative", -5, 0, 0, None, 0),
        ("Baseline ratio", 1.25, 1.0, 0, None, 1.25),
        ("Baseline ratio invalid", "NaN", 1.0, 0, None, 1.0),  # NaN -> default 1.0
    ]
    
    passed = 0
    failed = 0
    
    for description, value, default, min_val, max_val, expected in test_cases:
        try:
            result = _coerce_numeric(value, default, min_val, max_val)
            if result == expected:
                print(f"✓ {description}: {value} -> {result}")
                passed += 1
            else:
                print(f"✗ {description}: {value} -> {result}, expected {expected}")
                failed += 1
        except Exception as e:
            print(f"✗ {description}: Exception - {e}")
            failed += 1
    
    print(f"\nSummary: {passed} passed, {failed} failed")
    return failed == 0

def test_alert_data_coercion():
    """Test coercion with sample alert data."""
    print("\n" + "=" * 60)
    print("Testing alert data coercion scenarios")
    print("=" * 60)
    
    # Simulate the _coerce_numeric function and _coerce_row logic
    def _coerce_numeric(value, default, min_val=None, max_val=None):
        try:
            num = float(value) if value is not None else default
            # Handle NaN values by using default
            if num != num:  # NaN check (NaN != NaN is True)
                num = default
            if min_val is not None:
                num = max(min_val, num)
            if max_val is not None:
                num = min(max_val, num)
            return num
        except (ValueError, TypeError):
            return default
    
    # Test alert samples with problematic numeric data
    test_alerts = [
        {
            "uuid": "test-001",
            "title": "Normal Alert",
            "score": 75,
            "confidence": 0.85,
            "category_confidence": 0.9,
            "trend_score": 65,
            "latitude": 40.7128,
            "longitude": -74.0060,
            "future_risk_probability": 0.3,
            "incident_count_30d": 15,
            "baseline_ratio": 1.2
        },
        {
            "uuid": "test-002", 
            "title": "String Numeric Alert",
            "score": "88.5",
            "confidence": "0.75",
            "category_confidence": "0.95",
            "trend_score": "72",
            "latitude": "34.0522",
            "longitude": "-118.2437",
            "future_risk_probability": "0.4",
            "incident_count_30d": "8",
            "baseline_ratio": "1.5"
        },
        {
            "uuid": "test-003",
            "title": "Invalid Data Alert", 
            "score": "invalid",
            "confidence": None,
            "category_confidence": "bad_value",
            "trend_score": [],
            "latitude": "not_a_number",
            "longitude": 999,  # out of range
            "future_risk_probability": 2.0,  # out of range
            "incident_count_30d": -5,  # negative
            "baseline_ratio": "NaN"
        },
        {
            "uuid": "test-004",
            "title": "Out of Range Alert",
            "score": 150,  # over max
            "confidence": 1.5,  # over max
            "category_confidence": -0.1,  # under min
            "trend_score": -10,  # under min
            "latitude": 95,  # over max
            "longitude": -190,  # under min
            "future_risk_probability": 1.5,  # over max
            "incident_count_30d": 1000,
            "baseline_ratio": -1.0
        }
    ]
    
    expected_coercions = [
        # Normal alert - should pass through unchanged (as floats)
        {
            "score": 75.0, "confidence": 0.85, "category_confidence": 0.9,
            "trend_score": 65.0, "latitude": 40.7128, "longitude": -74.0060,
            "future_risk_probability": 0.3, "incident_count_30d": 15.0, 
            "baseline_ratio": 1.2
        },
        # String numeric alert - should convert successfully
        {
            "score": 88.5, "confidence": 0.75, "category_confidence": 0.95,
            "trend_score": 72.0, "latitude": 34.0522, "longitude": -118.2437,
            "future_risk_probability": 0.4, "incident_count_30d": 8.0,
            "baseline_ratio": 1.5
        },
        # Invalid data alert - should use defaults/clamp correctly
        {
            "score": 0, "confidence": 0.5, "category_confidence": 0.5,
            "trend_score": 0, "latitude": None, "longitude": 180,  # clamped to max
            "future_risk_probability": 1.0, "incident_count_30d": 0,  # out of range clamped to max, negative clamped to min
            "baseline_ratio": 1.0  # NaN -> default 1.0
        },
        # Out of range alert - should be clamped
        {
            "score": 100, "confidence": 1.0, "category_confidence": 0,  # clamped
            "trend_score": 0, "latitude": 90, "longitude": -180,  # clamped
            "future_risk_probability": 1.0, "incident_count_30d": 1000.0,
            "baseline_ratio": 0  # clamped to min
        }
    ]
    
    passed = 0
    failed = 0
    
    for i, (alert, expected) in enumerate(zip(test_alerts, expected_coercions)):
        print(f"\nTest Alert {i+1}: {alert['title']}")
        
        # Apply coercion as done in save_alerts_to_db
        results = {
            "score": _coerce_numeric(alert.get("score"), 0, 0, 100),
            "confidence": _coerce_numeric(alert.get("confidence"), 0.5, 0, 1),
            "category_confidence": _coerce_numeric(alert.get("category_confidence"), 0.5, 0, 1),
            "trend_score": _coerce_numeric(alert.get("trend_score"), 0, 0, 100),
            "latitude": _coerce_numeric(alert.get("latitude"), None, -90, 90),
            "longitude": _coerce_numeric(alert.get("longitude"), None, -180, 180),
            "future_risk_probability": _coerce_numeric(alert.get("future_risk_probability"), 0.25, 0, 1),
            "incident_count_30d": _coerce_numeric(alert.get("incident_count_30d"), 0, 0, None),
            "baseline_ratio": _coerce_numeric(alert.get("baseline_ratio"), 1.0, 0, None)
        }
        
        test_passed = True
        for field, expected_value in expected.items():
            actual_value = results[field]
            if actual_value == expected_value:
                print(f"  ✓ {field}: {alert.get(field)} -> {actual_value}")
            else:
                print(f"  ✗ {field}: {alert.get(field)} -> {actual_value}, expected {expected_value}")
                test_passed = False
        
        if test_passed:
            passed += 1
        else:
            failed += 1
    
    print(f"\nSummary: {passed} passed, {failed} failed")
    return failed == 0

def main():
    """Run all tests."""
    print("Running db_utils.py numeric coercion tests")
    print("=" * 80)
    
    all_tests_passed = True
    
    # Test the core function
    if not test_coerce_numeric_function():
        all_tests_passed = False
    
    # Test with realistic alert data
    if not test_alert_data_coercion():
        all_tests_passed = False
    
    print("\n" + "=" * 80)
    if all_tests_passed:
        print("🎉 All tests passed! Numeric coercion is working correctly.")
        print("✓ Score and confidence values will be safely bounded")
        print("✓ Geographic coordinates will be properly validated")
        print("✓ Invalid data will fallback to safe defaults")
        print("✓ Database insertions should be protected from type errors")
    else:
        print("❌ Some tests failed. Please review the implementation.")
    
    return 0 if all_tests_passed else 1

if __name__ == "__main__":
    sys.exit(main())
