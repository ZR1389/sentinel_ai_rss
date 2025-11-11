#!/usr/bin/env python3
"""
Test enhanced location matching in advisor.py after city_utils integration.
This test validates the improved _validate_location_match function.
"""

import sys
import os
# Add the root directory to the path so we can import advisor
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from advisor import _validate_location_match

def test_enhanced_location_matching():
    """Test the enhanced location matching functionality"""
    
    print("=== Testing Enhanced Location Matching with city_utils ===\n")
    
    # Test cases with different location scenarios
    test_cases = [
        {
            "name": "Exact city match",
            "query": "Budapest",
            "alert_data": {"city": "Budapest", "country": "Hungary", "region": "Central Hungary"},
            "expected_score_min": 90
        },
        {
            "name": "City substring match",
            "query": "New York",
            "alert_data": {"city": "New York City", "country": "United States", "region": "New York"},
            "expected_score_min": 85
        },
        {
            "name": "Region match when city doesn't match",
            "query": "California",
            "alert_data": {"city": "Los Angeles", "country": "United States", "region": "California"},
            "expected_score_min": 70
        },
        {
            "name": "Country match",
            "query": "France",
            "alert_data": {"city": "Lyon", "country": "France", "region": "Auvergne-Rhône-Alpes"},
            "expected_score_min": 55
        },
        {
            "name": "Geographic mismatch (Budapest vs Cairo)",
            "query": "Budapest",
            "alert_data": {"city": "Cairo", "country": "Egypt", "region": "Cairo Governorate"},
            "expected_score_max": 30
        },
        {
            "name": "Fuzzy matching - partial city name",
            "query": "Amsterdam security",
            "alert_data": {"city": "Amsterdam", "country": "Netherlands", "region": "North Holland"},
            "expected_score_min": 85
        },
        {
            "name": "Empty query",
            "query": "",
            "alert_data": {"city": "Tokyo", "country": "Japan", "region": "Kantō"},
            "expected_score_max": 10
        },
        {
            "name": "Missing alert data",
            "query": "London",
            "alert_data": {"city": "", "country": "", "region": ""},
            "expected_score_max": 15
        }
    ]
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test {i}: {test_case['name']}")
        print(f"  Query: '{test_case['query']}'")
        print(f"  Alert: {test_case['alert_data']}")
        
        try:
            score, matched_name, warning = _validate_location_match(
                test_case['query'], 
                test_case['alert_data']
            )
            
            print(f"  Result: score={score:.1f}, matched='{matched_name}'")
            if warning:
                print(f"  Warning: {warning}")
            
            # Validate expectations
            success = True
            if 'expected_score_min' in test_case:
                if score < test_case['expected_score_min']:
                    print(f"  ❌ FAIL: Expected score >= {test_case['expected_score_min']}, got {score:.1f}")
                    success = False
                else:
                    print(f"  ✅ PASS: Score {score:.1f} >= {test_case['expected_score_min']}")
            
            if 'expected_score_max' in test_case:
                if score > test_case['expected_score_max']:
                    print(f"  ❌ FAIL: Expected score <= {test_case['expected_score_max']}, got {score:.1f}")
                    success = False
                else:
                    print(f"  ✅ PASS: Score {score:.1f} <= {test_case['expected_score_max']}")
            
            results.append({
                'test': test_case['name'],
                'success': success,
                'score': score,
                'matched_name': matched_name,
                'warning': warning
            })
            
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            results.append({
                'test': test_case['name'],
                'success': False,
                'error': str(e)
            })
        
        print()
    
    # Summary
    passed = sum(1 for r in results if r.get('success', False))
    total = len(results)
    
    print(f"=== Test Summary ===")
    print(f"Passed: {passed}/{total}")
    print(f"Failed: {total - passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed! Enhanced location matching is working correctly.")
    else:
        print("⚠️ Some tests failed. Review the enhanced location matching logic.")
    
    return results

def test_city_utils_integration():
    """Test that city_utils integration is working"""
    
    print("=== Testing city_utils Integration ===\n")
    
    try:
        # Test direct import
        from city_utils import fuzzy_match_city, normalize_city_country, get_country_for_city
        print("✅ Successfully imported city_utils functions")
        
        # Test fuzzy matching
        match = fuzzy_match_city("Amsterdam security alert")
        print(f"✅ fuzzy_match_city('Amsterdam security alert') = {match}")
        
        # Test normalization
        city, country = normalize_city_country("budapest", "hungary")
        print(f"✅ normalize_city_country('budapest', 'hungary') = ({city}, {country})")
        
        return True
        
    except ImportError as e:
        print(f"❌ city_utils import failed: {e}")
        print("Using fallback implementations")
        return False
    except Exception as e:
        print(f"❌ city_utils integration error: {e}")
        return False

if __name__ == "__main__":
    print("Testing Enhanced Location Matching with city_utils Integration\n")
    
    # Test city_utils integration first
    city_utils_working = test_city_utils_integration()
    print()
    
    # Test enhanced location matching
    results = test_enhanced_location_matching()
    
    # Overall assessment
    print("\n=== Overall Assessment ===")
    if city_utils_working:
        print("✅ city_utils integration successful")
    else:
        print("⚠️ city_utils using fallback implementations")
    
    passed = sum(1 for r in results if r.get('success', False))
    total = len(results)
    
    if passed == total:
        print("✅ Enhanced location matching fully functional")
        print("🎯 Ready for production use with improved geographic validation")
    else:
        print(f"⚠️ Location matching needs refinement ({passed}/{total} tests passed)")
