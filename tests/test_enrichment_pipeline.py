#!/usr/bin/env python3
"""
Test script for the new modular enrichment pipeline.
"""

import sys
import os
import json
from datetime import datetime

# Add the parent directory to the Python path so we can import from root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_enrichment_pipeline():
    """Test the new enrichment pipeline with a sample alert."""
    
    # Sample test alert - more realistic to avoid filtering
    test_alert = {
        "uuid": "test-alert-123",
        "title": "Data Breach Detected at Healthcare Facility",
        "summary": "A significant data breach was discovered at Regional Medical Center affecting patient records. The incident is under investigation by cybersecurity teams and authorities have been notified.",
        "city": "Boston",
        "region": "Massachusetts", 
        "country": "USA",
        "tags": ["cybersecurity", "healthcare", "data-breach", "investigation"],
        "timestamp": datetime.utcnow().isoformat(),
        "source": "security_feed",
        "url": "https://example.com/test-alert",
        "category": "Cybersecurity",
        "threat_score": 0.75,  # Score between 0 and 1
        "confidence": 0.85,
        "score": 0.75,  # Make sure score is in valid range
        # Add some baseline data to avoid zero-incident filtering
        "incident_count_30d": 3,
        "recent_count_7d": 1
    }
    
    print("Testing modular enrichment pipeline...")
    print(f"Input alert: {test_alert['title']}")
    
    try:
        # Test the new enrichment pipeline
        from enrichment_stages import enrich_single_alert, get_enrichment_pipeline
        
        pipeline = get_enrichment_pipeline()
        print(f"Pipeline created with {len(pipeline.stages)} stages")
        
        # Test individual pipeline
        enriched_alert = enrich_single_alert(test_alert)
        
        if enriched_alert is None:
            print("❌ Alert was filtered out by the pipeline")
            return False
        
        print("✅ Alert successfully enriched")
        
        # Check key fields were added
        expected_fields = [
            "overall_confidence", "gpt_summary", "category", "domains"
        ]
        
        missing_fields = []
        for field in expected_fields:
            if field not in enriched_alert:
                missing_fields.append(field)
        
        if missing_fields:
            print(f"⚠️  Missing expected fields: {missing_fields}")
        else:
            print("✅ All expected fields present")
        
        # Show some key results
        print(f"\nEnrichment Results:")
        print(f"  - Category: {enriched_alert.get('category', 'N/A')}")
        print(f"  - Confidence: {enriched_alert.get('overall_confidence', 0):.2f}")
        print(f"  - Threat Score: {enriched_alert.get('threat_score', 0)}")
        print(f"  - Domains: {enriched_alert.get('domains', [])}")
        print(f"  - Summary Length: {len(enriched_alert.get('gpt_summary', ''))}")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Enrichment failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_legacy_compatibility():
    """Test that the legacy function still works."""
    
    test_alert = {
        "uuid": "legacy-test-456",
        "title": "Malware Attack on Corporate Network",
        "summary": "A sophisticated malware attack has been detected on the corporate network infrastructure. IT security teams are responding and containment measures are being implemented.",
        "city": "Seattle",
        "region": "Washington",
        "country": "USA",
        "tags": ["malware", "corporate", "network"],
        "timestamp": datetime.utcnow().isoformat(),
        "source": "security_alerts",
        "url": "https://example.com/legacy-test",
        "category": "Cybersecurity",
        "threat_score": 0.80,  # Score between 0 and 1
        "score": 0.80,  # Make sure score is in valid range
        # Add baseline data to avoid filtering
        "incident_count_30d": 5,
        "recent_count_7d": 2
    }
    
    print("\n" + "="*50)
    print("Testing legacy compatibility...")
    print(f"Input alert: {test_alert['title']}")
    
    try:
        # Test the threat_engine function (should use new pipeline internally)
        from services.threat_engine import summarize_single_alert
        
        enriched_alert = summarize_single_alert(test_alert)
        
        if enriched_alert is None:
            print("❌ Alert was filtered out")
            return False
        
        print("✅ Legacy function successfully processed alert")
        print(f"  - Category: {enriched_alert.get('category', 'N/A')}")
        print(f"  - Confidence: {enriched_alert.get('overall_confidence', 0):.2f}")
        
        return True
        
    except Exception as e:
        print(f"❌ Legacy compatibility test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Sentinel AI - Enrichment Pipeline Test")
    print("="*50)
    
    # Setup basic environment
    os.environ["USE_MODULAR_ENRICHMENT"] = "true"
    
    # Run tests
    pipeline_test_passed = test_enrichment_pipeline()
    legacy_test_passed = test_legacy_compatibility()
    
    print("\n" + "="*50)
    print("TEST RESULTS:")
    print(f"  Modular Pipeline: {'✅ PASS' if pipeline_test_passed else '❌ FAIL'}")
    print(f"  Legacy Compatibility: {'✅ PASS' if legacy_test_passed else '❌ FAIL'}")
    
    if pipeline_test_passed and legacy_test_passed:
        print("\n🎉 All tests passed! The enrichment pipeline is ready.")
        sys.exit(0)
    else:
        print("\n💥 Some tests failed. Check the output above.")
        sys.exit(1)
