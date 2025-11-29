#!/usr/bin/env python3
"""
Smoke test for advisor.py gating logic.
Tests:
1. Normal path: good location match + sufficient data → full advisory
2. Gate path: severe mismatch → "NO INTELLIGENCE AVAILABLE"
3. Gate path: low confidence → blocked
4. Gate path: insufficient data → blocked
"""

import sys
import logging
from typing import Dict, Any

# Mock minimal dependencies
sys.path.insert(0, '/home/zika/sentinel_ai_rss')

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def test_normal_path():
    """Test normal advisory generation with good data"""
    from advisor import render_advisory
    
    alert: Dict[str, Any] = {
        "city": "Belgrade",
        "region": "Central Serbia",
        "country": "Serbia",
        "category": "Civil Unrest",
        "subcategory": "Protest",
        "label": "MODERATE",
        "score": 0.65,
        "confidence": 0.75,
        "domains": ["civil_unrest", "travel_mobility"],
        "title": "Large protest expected in central Belgrade",
        "summary": "Thousands expected to gather near Parliament for political demonstration",
        "incident_count_30d": 12,
        "trend_direction": "increasing",
        "baseline_ratio": 1.8,
        "anomaly_flag": False,
        "sources": [{"name": "Local News Serbia", "link": "https://example.com"}],
    }
    
    user_message = "What is the security situation in Serbia?"
    profile_data = {"location": "Belgrade, Serbia", "role": "traveler"}
    
    logger.info("\n" + "="*60)
    logger.info("TEST 1: Normal Path (Good Match + Sufficient Data)")
    logger.info("="*60)
    logger.info(f"Query: {user_message}")
    logger.info(f"Profile Location: {profile_data['location']}")
    logger.info(f"Alert Location: {alert['city']}, {alert['country']}")
    logger.info(f"Confidence: {alert['confidence']}, Incidents: {alert['incident_count_30d']}")
    
    try:
        result = render_advisory(alert, user_message, profile_data)
        
        if "NO INTELLIGENCE AVAILABLE" in result:
            logger.error("❌ FAIL: Gate triggered when it shouldn't have")
            logger.error(f"Result preview: {result[:500]}")
            return False
        else:
            logger.info("✅ PASS: Normal advisory generated")
            # Check for key sections
            required_sections = [
                "BULLETPOINT RISK SUMMARY",
                "WHAT TO DO NOW",
                "HOW TO PREPARE"
            ]
            missing = [s for s in required_sections if s not in result]
            if missing:
                logger.warning(f"⚠️  Missing sections: {missing}")
            else:
                logger.info("✅ All key sections present")
            logger.info(f"\nAdvisory preview (first 800 chars):\n{result[:800]}...\n")
            return True
    except Exception as e:
        logger.error(f"❌ FAIL: Exception during normal path: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_location_mismatch():
    """Test gating on severe location mismatch"""
    from advisor import render_advisory
    
    alert: Dict[str, Any] = {
        "city": "Tel Aviv",
        "region": "Tel Aviv District",
        "country": "Israel",
        "category": "Terrorism",
        "label": "HIGH",
        "score": 0.85,
        "confidence": 0.80,
        "domains": ["terrorism", "physical_safety"],
        "title": "Security incident in Tel Aviv",
        "summary": "Alert issued for central Tel Aviv area",
        "incident_count_30d": 8,
        "trend_direction": "stable",
        "baseline_ratio": 1.2,
    }
    
    user_message = "What is the security situation in Serbia?"
    profile_data = {"location": "Belgrade, Serbia"}
    
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Location Mismatch Gate (Serbia query vs Israel data)")
    logger.info("="*60)
    logger.info(f"Query: {user_message}")
    logger.info(f"Profile Location: {profile_data['location']}")
    logger.info(f"Alert Location: {alert['city']}, {alert['country']}")
    
    try:
        result = render_advisory(alert, user_message, profile_data)
        
        if "NO INTELLIGENCE AVAILABLE" in result:
            logger.info("✅ PASS: Gate triggered correctly")
            if "severe location mismatch" in result.lower():
                logger.info("✅ Correct reason: severe location mismatch")
            if "DATA PROVENANCE" in result:
                logger.info("✅ Provenance section present")
            logger.info(f"\nGate response:\n{result}\n")
            return True
        else:
            logger.error("❌ FAIL: Gate should have triggered but didn't")
            logger.error(f"Result preview: {result[:500]}")
            return False
    except Exception as e:
        logger.error(f"❌ FAIL: Exception during mismatch test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_low_confidence():
    """Test gating on low confidence"""
    from advisor import render_advisory
    
    alert: Dict[str, Any] = {
        "city": "Belgrade",
        "region": "Central Serbia",
        "country": "Serbia",
        "category": "Other",
        "label": "LOW",
        "score": 0.25,
        "confidence": 0.30,  # Below 0.40 threshold
        "domains": ["physical_safety"],
        "title": "Unverified report",
        "summary": "Low confidence event",
        "incident_count_30d": 6,
        "trend_direction": "stable",
        "baseline_ratio": 1.0,
    }
    
    user_message = "What's happening in Belgrade?"
    profile_data = {"location": "Belgrade"}
    
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Low Confidence Gate (30% confidence < 40% threshold)")
    logger.info("="*60)
    logger.info(f"Alert Confidence: {alert['confidence']}")
    logger.info(f"Location Match: Good (Belgrade)")
    
    try:
        result = render_advisory(alert, user_message, profile_data)
        
        if "NO INTELLIGENCE AVAILABLE" in result:
            logger.info("✅ PASS: Gate triggered correctly")
            if "low confidence" in result.lower():
                logger.info("✅ Correct reason: low confidence")
            logger.info(f"\nGate response:\n{result}\n")
            return True
        else:
            logger.error("❌ FAIL: Gate should have triggered for low confidence")
            logger.error(f"Result preview: {result[:500]}")
            return False
    except Exception as e:
        logger.error(f"❌ FAIL: Exception during low confidence test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_insufficient_data():
    """Test gating on insufficient data volume"""
    from advisor import render_advisory
    
    alert: Dict[str, Any] = {
        "city": "Belgrade",
        "region": "Central Serbia",
        "country": "Serbia",
        "category": "Physical Safety",
        "label": "MODERATE",
        "score": 0.60,
        "confidence": 0.70,
        "domains": ["physical_safety"],
        "title": "Isolated incident",
        "summary": "Single event report",
        "incident_count_30d": 2,  # < 5 threshold
        "trend_direction": "stable",
        "baseline_ratio": 1.0,
    }
    
    user_message = "Security in Belgrade?"
    profile_data = {"location": "Belgrade"}
    
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Insufficient Data Gate (2 incidents < 5 threshold)")
    logger.info("="*60)
    logger.info(f"Incident Count: {alert['incident_count_30d']}")
    logger.info(f"Location Match: Good (Belgrade)")
    logger.info(f"Confidence: {alert['confidence']}")
    
    try:
        result = render_advisory(alert, user_message, profile_data)
        
        if "NO INTELLIGENCE AVAILABLE" in result:
            logger.info("✅ PASS: Gate triggered correctly")
            if "insufficient data" in result.lower():
                logger.info("✅ Correct reason: insufficient data volume")
            logger.info(f"\nGate response:\n{result}\n")
            return True
        else:
            logger.error("❌ FAIL: Gate should have triggered for insufficient data")
            logger.error(f"Result preview: {result[:500]}")
            return False
    except Exception as e:
        logger.error(f"❌ FAIL: Exception during insufficient data test: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    logger.info("\n" + "#"*60)
    logger.info("# ADVISOR GATING LOGIC SMOKE TEST")
    logger.info("#"*60)
    
    results = []
    
    # Run all tests
    results.append(("Normal Path", test_normal_path()))
    results.append(("Location Mismatch", test_location_mismatch()))
    results.append(("Low Confidence", test_low_confidence()))
    results.append(("Insufficient Data", test_insufficient_data()))
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    logger.info("="*60)
    logger.info(f"Result: {passed_count}/{total_count} tests passed")
    logger.info("="*60 + "\n")
    
    return 0 if passed_count == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
