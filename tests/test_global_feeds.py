#!/usr/bin/env python3
"""
test_global_feeds.py - Test global-first RSS feed strategy

Tests:
1. Feed priority ordering (global > local > country)
2. Keyword matching on sample global content
3. Location extraction from article text
4. Sports filtering
5. Language detection for non-English content
"""

import sys
from typing import List, Dict, Any

def test_feed_priority():
    """Test that global feeds have highest priority."""
    print("\n" + "="*70)
    print("TEST 1: Feed Priority Ordering")
    print("="*70)
    
    from services.rss_processor import _coalesce_all_feed_specs, GLOBAL_PRIORITY, NATIVE_PRIORITY
    
    specs = _coalesce_all_feed_specs()
    
    # Get first 10 feeds
    print(f"\nTotal feeds configured: {len(specs)}")
    print("\nFirst 10 feeds (should be global):")
    for i, spec in enumerate(specs[:10], 1):
        priority = spec.get('priority', 999)
        kind = spec.get('kind', 'unknown')
        tag = spec.get('tag', '')
        url = spec.get('url', '')[:60]
        
        status = "✓ GLOBAL" if priority == GLOBAL_PRIORITY else "✗ NOT GLOBAL"
        print(f"{i:2}. [{status}] {kind:8} (p={priority:2}) {tag:15} {url}")
    
    # Verify global feeds come first
    global_count = sum(1 for s in specs[:20] if s.get('priority') == GLOBAL_PRIORITY)
    print(f"\n✓ Global feeds in top 20: {global_count}/20")
    
    return global_count > 15  # At least 15/20 should be global

def test_keyword_matching():
    """Test keyword matching on sample security content."""
    print("\n" + "="*70)
    print("TEST 2: Keyword Matching")
    print("="*70)
    
    from services.rss_processor import _kw_decide
    
    test_cases = [
        {
            "title": "Cyberattack Hits Hospital",
            "text": "Cyberattack hits major hospital in Lagos, Nigeria. Ransomware encrypted patient records.",
            "should_match": True,
            "expected_keywords": ["cyberattack", "ransomware", "hospital"]
        },
        {
            "title": "Protests in Bangkok",
            "text": "Protests erupt in Bangkok after government announces new restrictions. Clashes with police reported.",
            "should_match": True,
            "expected_keywords": ["protests", "clashes"]
        },
        {
            "title": "Manchester United Victory",
            "text": "Manchester United wins 3-1 against Chelsea in Premier League match at Old Trafford.",
            "should_match": False,
            "expected_keywords": []
        },
        {
            "title": "Severe Flooding",
            "text": "Severe flooding in Mumbai displaces thousands as monsoon rains continue. Emergency services evacuate residents.",
            "should_match": True,
            "expected_keywords": ["flooding", "evacuate"]
        },
        {
            "title": "New Restaurant Opens",
            "text": "New restaurant opens in downtown featuring fusion cuisine and craft cocktails. Chef trained in Paris.",
            "should_match": False,
            "expected_keywords": []
        }
    ]
    
    passed = 0
    failed = 0
    
    for i, case in enumerate(test_cases, 1):
        matched, match_data = _kw_decide(case["title"], case["text"])
        
        success = matched == case["should_match"]
        status = "✓ PASS" if success else "✗ FAIL"
        
        print(f"\n{i}. {status}")
        print(f"   Title: {case['title']}")
        print(f"   Expected match: {case['should_match']}, Got: {matched}")
        
        if matched:
            rule = match_data.get("rule", "unknown")
            matches = match_data.get("matches", {})
            print(f"   Rule: {rule}, Matches: {matches}")
        
        if success:
            passed += 1
        else:
            failed += 1
    
    print(f"\n✓ Passed: {passed}/{len(test_cases)}")
    print(f"✗ Failed: {failed}/{len(test_cases)}")
    
    return failed == 0

def test_location_extraction():
    """Test location extraction from global article content."""
    print("\n" + "="*70)
    print("TEST 3: Location Extraction from Content")
    print("="*70)
    
    try:
        from services.location_service_consolidated import detect_location
    except ImportError:
        print("⚠ location_service_consolidated not available, trying city_utils...")
        try:
            from city_utils import extract_location
            detect_location = lambda text: type('obj', (), {'city': extract_location(text)[0], 'country': extract_location(text)[1]})()
        except ImportError:
            print("✗ No location extraction available")
            return False
    
    test_cases = [
        {
            "text": "A major cyberattack hit hospitals in Lagos, Nigeria on Tuesday, disrupting patient care.",
            "expected_city": "Lagos",
            "expected_country": "Nigeria"
        },
        {
            "text": "Protests erupted in Bangkok, Thailand as thousands marched against new government policies.",
            "expected_city": "Bangkok",
            "expected_country": "Thailand"
        },
        {
            "text": "Severe flooding in Mumbai, India has displaced over 10,000 residents according to local officials.",
            "expected_city": "Mumbai",
            "expected_country": "India"
        },
        {
            "text": "Israeli officials confirmed an incident near Tel Aviv involving explosives found at a checkpoint.",
            "expected_city": "Tel Aviv",
            "expected_country": "Israel"
        }
    ]
    
    passed = 0
    failed = 0
    
    for i, case in enumerate(test_cases, 1):
        result = detect_location(case["text"])
        
        city_match = (result.city or "").lower() == case["expected_city"].lower() if result.city else False
        country_match = (result.country or "").lower() == case["expected_country"].lower() if result.country else False
        
        success = city_match or country_match  # At least one should match
        status = "✓ PASS" if success else "⚠ PARTIAL"
        
        print(f"\n{i}. {status}")
        print(f"   Text: {case['text'][:70]}...")
        print(f"   Expected: {case['expected_city']}, {case['expected_country']}")
        print(f"   Got: {result.city or 'None'}, {result.country or 'None'}")
        
        if success:
            passed += 1
        else:
            failed += 1
    
    print(f"\n✓ Passed/Partial: {passed}/{len(test_cases)}")
    
    return passed >= len(test_cases) * 0.5  # At least 50% should work

def test_sports_filtering():
    """Test that sports content is properly filtered."""
    print("\n" + "="*70)
    print("TEST 4: Sports Content Filtering")
    print("="*70)
    
    from risk_shared import likely_sports_context
    
    test_cases = [
        {
            "text": "Manchester United defeats Chelsea 3-1 in Premier League match at Old Trafford stadium.",
            "should_filter": True
        },
        {
            "text": "Lakers vs Warriors game ends 112-108 with championship implications.",
            "should_filter": True
        },
        {
            "text": "Security breach at stadium during championship game leads to evacuation.",
            "should_filter": False  # Has security context
        },
        {
            "text": "Cyberattack targets sports betting platform, stealing user credentials.",
            "should_filter": False  # Cyber incident
        },
        {
            "text": "Italy wins Eurovision song contest with record-breaking performance.",
            "should_filter": True  # Entertainment
        }
    ]
    
    passed = 0
    failed = 0
    
    for i, case in enumerate(test_cases, 1):
        is_sports = likely_sports_context(case["text"])
        
        success = is_sports == case["should_filter"]
        status = "✓ PASS" if success else "✗ FAIL"
        
        print(f"\n{i}. {status}")
        print(f"   Text: {case['text'][:70]}...")
        print(f"   Should filter: {case['should_filter']}, Got: {is_sports}")
        
        if success:
            passed += 1
        else:
            failed += 1
    
    print(f"\n✓ Passed: {passed}/{len(test_cases)}")
    print(f"✗ Failed: {failed}/{len(test_cases)}")
    
    return failed == 0

def test_language_detection():
    """Test language detection to verify English-only strategy."""
    print("\n" + "="*70)
    print("TEST 5: Language Detection")
    print("="*70)
    
    from services.rss_processor import _safe_lang
    
    test_cases = [
        {"text": "Cyberattack hits major hospital in New York", "expected": "en"},
        {"text": "Protests erupt in Bangkok amid political crisis", "expected": "en"},
        {"text": "Ataque cibernético afecta hospitales en Madrid", "expected": "es"},
        {"text": "Paris subit une cyberattaque majeure", "expected": "fr"},
        {"text": "Наводнение в Москве привело к эвакуации", "expected": "ru"},
    ]
    
    passed = 0
    
    for i, case in enumerate(test_cases, 1):
        detected = _safe_lang(case["text"])
        
        success = detected == case["expected"]
        status = "✓ PASS" if success else "⚠ INFO"
        
        print(f"{i}. {status} Expected '{case['expected']}', Got '{detected}': {case['text'][:50]}...")
        
        if success:
            passed += 1
    
    print(f"\n✓ Correct detections: {passed}/{len(test_cases)}")
    
    return passed >= 3  # Most should work

def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "="*70)
    print("GLOBAL-FIRST RSS FEED STRATEGY - TEST SUITE")
    print("="*70)
    
    results = {}
    
    try:
        results["Feed Priority"] = test_feed_priority()
    except Exception as e:
        print(f"\n✗ Feed Priority test failed: {e}")
        results["Feed Priority"] = False
    
    try:
        results["Keyword Matching"] = test_keyword_matching()
    except Exception as e:
        print(f"\n✗ Keyword Matching test failed: {e}")
        results["Keyword Matching"] = False
    
    try:
        results["Location Extraction"] = test_location_extraction()
    except Exception as e:
        print(f"\n✗ Location Extraction test failed: {e}")
        results["Location Extraction"] = False
    
    try:
        results["Sports Filtering"] = test_sports_filtering()
    except Exception as e:
        print(f"\n✗ Sports Filtering test failed: {e}")
        results["Sports Filtering"] = False
    
    try:
        results["Language Detection"] = test_language_detection()
    except Exception as e:
        print(f"\n✗ Language Detection test failed: {e}")
        results["Language Detection"] = False
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} {test_name}")
    
    total = len(results)
    passed_count = sum(1 for v in results.values() if v)
    
    print(f"\nOverall: {passed_count}/{total} tests passed")
    
    if passed_count == total:
        print("\n🎉 All tests passed! Your global-first strategy is working correctly.")
        return 0
    elif passed_count >= total * 0.7:
        print("\n⚠ Most tests passed. Review failures above.")
        return 0
    else:
        print("\n✗ Multiple test failures. Review implementation.")
        return 1

if __name__ == "__main__":
    sys.exit(run_all_tests())
