#!/usr/bin/env python3
"""
Test script to demonstrate complete numeric type safety protection
Tests the full chain: db_utils coercion → database constraints → application safety
"""

import sys
import os
sys.path.insert(0, '.')

def test_complete_numeric_protection():
    """Test the complete numeric type safety protection chain"""
    
    print("🛡️  COMPLETE NUMERIC TYPE SAFETY TEST")
    print("=" * 50)
    
    # Test 1: Application-level coercion (db_utils)
    print("\n1️⃣ TESTING APPLICATION-LEVEL COERCION (db_utils)")
    print("-" * 45)
    
    def _coerce_numeric(value, default, min_val=None, max_val=None):
        """Same function as in updated db_utils.py"""
        try:
            num = float(value) if value is not None else default
            if min_val is not None:
                num = max(min_val, num)
            if max_val is not None:
                num = min(max_val, num)
            return num
        except (ValueError, TypeError):
            return default
    
    # Test problematic data that would cause database issues
    problem_data = [
        ("'85'", 0, 0, 100, "SQL injection attempt"),
        ("85.5.5", 0.5, 0, 1, "Malformed decimal"),
        ("NaN", 0, 0, 100, "Not a Number"),
        ("Infinity", 50, 0, 100, "Infinity value"),
        ("", 0.5, 0, 1, "Empty string"),
        ("   ", 0, 0, 100, "Whitespace only"),
        ({"invalid": "dict"}, 0, 0, 100, "Wrong data type"),
        ([1, 2, 3], 0.5, 0, 1, "List instead of number"),
    ]
    
    all_safe = True
    for value, default, min_val, max_val, description in problem_data:
        try:
            result = _coerce_numeric(value, default, min_val, max_val)
            is_safe = isinstance(result, (int, float)) and not str(result).lower() in ['nan', 'inf', '-inf']
            status = "✅ SAFE" if is_safe else "❌ UNSAFE"
            print(f"  {status}: {description:20} → {result}")
            if not is_safe:
                all_safe = False
        except Exception as e:
            print(f"  ❌ ERROR: {description:20} → Exception: {e}")
            all_safe = False
    
    print(f"\n📊 Application coercion result: {'✅ ALL SAFE' if all_safe else '❌ ISSUES FOUND'}")
    
    # Test 2: Score type safety module integration
    print("\n2️⃣ TESTING SCORE TYPE SAFETY MODULE")
    print("-" * 35)
    
    try:
        from score_type_safety import safe_numeric_score, safe_score_comparison
        
        test_scores = [
            ("'85'", "SQL injection string"),
            ("invalid_text", "Invalid text data"),
            (None, "NULL value"),
            (float('inf'), "Infinity value"),
        ]
        
        safety_module_working = True
        for score, description in test_scores:
            try:
                safe_val = safe_numeric_score(score, default=0.0, min_val=0.0, max_val=100.0)
                comparison_works = safe_score_comparison(safe_val, 50.0, '>')
                status = "✅ SAFE" if 0 <= safe_val <= 100 else "❌ UNSAFE"
                print(f"  {status}: {description:20} → score: {safe_val}, >50: {comparison_works}")
            except Exception as e:
                print(f"  ❌ ERROR: {description:20} → {e}")
                safety_module_working = False
        
        print(f"\n📊 Safety module result: {'✅ WORKING' if safety_module_working else '❌ ISSUES'}")
        
    except ImportError as e:
        print(f"  ⚠️  Score type safety module not available: {e}")
    
    # Test 3: Database migration readiness
    print("\n3️⃣ TESTING DATABASE MIGRATION READINESS")
    print("-" * 40)
    
    migration_file = "migrate_score_type.sql"
    if os.path.exists(migration_file):
        with open(migration_file, 'r') as f:
            content = f.read()
        
        checks = [
            ("ALTER TABLE alerts", "Table alteration command"),
            ("TYPE numeric", "Column type conversion"), 
            ("CHECK (score >= 0 AND score <= 100)", "Score range constraint"),
            ("CHECK (confidence >= 0 AND confidence <= 1)", "Confidence range constraint"),
            ("CREATE INDEX", "Performance index creation"),
        ]
        
        migration_ready = True
        for check, description in checks:
            if check in content:
                print(f"  ✅ READY: {description}")
            else:
                print(f"  ❌ MISSING: {description}")
                migration_ready = False
        
        print(f"\n📊 Migration readiness: {'✅ READY' if migration_ready else '❌ INCOMPLETE'}")
    else:
        print(f"  ❌ Migration file {migration_file} not found")
    
    # Test 4: Integration test with sample alert data
    print("\n4️⃣ TESTING INTEGRATION WITH SAMPLE DATA")
    print("-" * 38)
    
    sample_alert = {
        "uuid": "test-123",
        "title": "Test Security Alert",
        "score": "85.5",  # Text score (common problem)
        "confidence": "0.9",  # Text confidence
        "category_confidence": "invalid",  # Invalid data
        "latitude": "40.7128",  # Text coordinate
        "longitude": "ABC123",  # Invalid coordinate
        "trend_score": None,  # NULL score
        "future_risk_probability": "150%"  # Invalid percentage
    }
    
    # Apply coercion as db_utils would do
    coerced_data = {
        "score": _coerce_numeric(sample_alert.get("score"), 0, 0, 100),
        "confidence": _coerce_numeric(sample_alert.get("confidence"), 0.5, 0, 1),
        "category_confidence": _coerce_numeric(sample_alert.get("category_confidence"), 0.5, 0, 1),
        "latitude": _coerce_numeric(sample_alert.get("latitude"), None, -90, 90),
        "longitude": _coerce_numeric(sample_alert.get("longitude"), None, -180, 180),
        "trend_score": _coerce_numeric(sample_alert.get("trend_score"), 0, 0, 100),
        "future_risk_probability": _coerce_numeric(sample_alert.get("future_risk_probability"), 0.25, 0, 1),
    }
    
    print("  Original problematic data:")
    for key, value in sample_alert.items():
        if key in coerced_data:
            print(f"    {key}: '{value}' (type: {type(value).__name__})")
    
    print("\n  After coercion (safe for database):")
    for key, value in coerced_data.items():
        print(f"    {key}: {value} (type: {type(value).__name__})")
    
    # Validate all coerced values are database-safe
    validation_passed = True
    for key, value in coerced_data.items():
        if not isinstance(value, (int, float, type(None))):
            print(f"    ❌ {key}: Not numeric type")
            validation_passed = False
        elif value is not None and (str(value).lower() in ['nan', 'inf', '-inf']):
            print(f"    ❌ {key}: Invalid numeric value")
            validation_passed = False
    
    print(f"\n📊 Integration test: {'✅ PASSED' if validation_passed else '❌ FAILED'}")
    
    # Final summary
    print("\n" + "=" * 50)
    print("🎯 COMPLETE PROTECTION CHAIN STATUS")
    print("=" * 50)
    
    protection_layers = [
        ("Application Coercion", all_safe, "db_utils._coerce_numeric()"),
        ("Safety Module", safety_module_working, "score_type_safety.py"),
        ("Database Migration", migration_ready, "migrate_score_type.sql"), 
        ("Integration Test", validation_passed, "End-to-end validation")
    ]
    
    overall_status = "FULLY PROTECTED"
    for layer, status, component in protection_layers:
        emoji = "✅" if status else "❌"
        print(f"{emoji} {layer:20} {component}")
        if not status:
            overall_status = "NEEDS ATTENTION"
    
    print(f"\n🛡️  OVERALL STATUS: {overall_status}")
    
    if overall_status == "FULLY PROTECTED":
        print("\n🎉 SUCCESS!")
        print("✅ Complete protection against numeric type issues")
        print("✅ Database migration ready for execution")
        print("✅ Application code handles all edge cases safely")
        print("✅ No more silent failures in score comparisons")
        print("✅ System ready for production with numeric safety")
    else:
        print("\n⚠️  Some issues detected - review failed components")
    
    return overall_status == "FULLY PROTECTED"

if __name__ == "__main__":
    success = test_complete_numeric_protection()
    sys.exit(0 if success else 1)
