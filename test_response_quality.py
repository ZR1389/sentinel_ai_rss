#!/usr/bin/env python3
"""
Test script for Response Quality Indicators
Simulates chat responses with different quality levels
"""

import json
from datetime import datetime, timedelta, timezone

def format_metadata_example(scenario_name, metadata):
    """Pretty print a metadata example"""
    print(f"\n{'='*60}")
    print(f"Scenario: {scenario_name}")
    print('='*60)
    print(json.dumps(metadata, indent=2))
    
    # Interpret the values
    print("\nInterpretation:")
    print(f"  • Sources: {metadata['sources_count']} {'(comprehensive)' if metadata['sources_count'] > 30 else '(limited)' if metadata['sources_count'] < 10 else '(good)'}")
    
    confidence = metadata['confidence_score']
    if confidence >= 0.75:
        print(f"  • Confidence: {confidence:.2f} - 🟢 High (reliable)")
    elif confidence >= 0.50:
        print(f"  • Confidence: {confidence:.2f} - 🟡 Medium (moderate)")
    else:
        print(f"  • Confidence: {confidence:.2f} - 🔴 Low (limited)")
    
    # Calculate data age
    last_updated = datetime.fromisoformat(metadata['last_updated'].replace('Z', '+00:00'))
    age_hours = (datetime.now(timezone.utc) - last_updated).total_seconds() / 3600
    
    if age_hours < 1:
        age_str = f"{int(age_hours * 60)} minutes ago"
    elif age_hours < 24:
        age_str = f"{int(age_hours)} hours ago"
    else:
        age_str = f"{int(age_hours / 24)} days ago"
    
    print(f"  • Data Age: {age_str} {'(fresh ✓)' if age_hours < 24 else '(stale ⚠️)'}")
    print(f"  • Refresh: {'Available 🔄' if metadata['can_refresh'] else 'Not needed'}")
    print(f"  • Processing: {metadata['processing_time_ms']}ms")

def main():
    print("\n" + "="*60)
    print("RESPONSE QUALITY INDICATORS - TEST EXAMPLES")
    print("="*60)
    
    # Scenario 1: High-Quality Response
    now = datetime.now(timezone.utc)
    format_metadata_example(
        "High-Quality Response (PRO user - Bogotá query)",
        {
            "sources_count": 45,
            "confidence_score": 0.89,
            "last_updated": (now - timedelta(minutes=30)).isoformat().replace('+00:00', 'Z'),
            "can_refresh": False,
            "processing_time_ms": 2341
        }
    )
    
    # Scenario 2: Stale Data
    format_metadata_example(
        "Stale Data (4 days old)",
        {
            "sources_count": 12,
            "confidence_score": 0.68,
            "last_updated": (now - timedelta(days=4)).isoformat().replace('+00:00', 'Z'),
            "can_refresh": True,
            "processing_time_ms": 1823
        }
    )
    
    # Scenario 3: Low Coverage
    format_metadata_example(
        "Low Coverage (obscure location)",
        {
            "sources_count": 3,
            "confidence_score": 0.42,
            "last_updated": (now - timedelta(hours=2)).isoformat().replace('+00:00', 'Z'),
            "can_refresh": True,
            "processing_time_ms": 1156
        }
    )
    
    # Scenario 4: No Sources (FREE tier echo)
    format_metadata_example(
        "FREE Tier Echo Response",
        {
            "sources_count": 0,
            "confidence_score": 0.0,
            "last_updated": now.isoformat().replace('+00:00', 'Z'),
            "can_refresh": False,
            "processing_time_ms": 42
        }
    )
    
    # Scenario 5: Fresh Data - No Refresh Needed
    format_metadata_example(
        "Fresh Data (Just updated)",
        {
            "sources_count": 28,
            "confidence_score": 0.91,
            "last_updated": (now - timedelta(minutes=15)).isoformat().replace('+00:00', 'Z'),
            "can_refresh": False,
            "processing_time_ms": 2156
        }
    )
    
    print("\n" + "="*60)
    print("FRONTEND INTEGRATION GUIDANCE")
    print("="*60)
    print("""
Color Coding:
  • 🟢 Green (≥0.75): High confidence - reliable intelligence
  • 🟡 Yellow (0.50-0.74): Medium confidence - moderate reliability
  • 🔴 Red (<0.50): Low confidence - limited intelligence

Refresh Logic:
  • can_refresh: true → Show refresh button (data >1 hour old)
  • can_refresh: false → Hide refresh button (data is fresh)

Warnings to Display:
  • confidence_score < 0.50: "Limited intelligence available"
  • sources_count < 5: "Very limited coverage for this query"
  • Data age >7 days: "Data may be outdated - consider refreshing"
  • sources_count == 0: "No intelligence sources found"
    """)
    
    print("\n" + "="*60)
    print("EXAMPLE API RESPONSE")
    print("="*60)
    example_response = {
        "ok": True,
        "reply": "Based on current intelligence from 45 sources across Bogotá, the security situation shows moderate risk levels...",
        "plan": "PRO",
        "quota": {
            "used": 15,
            "limit": 500,
            "plan": "PRO"
        },
        "metadata": {
            "sources_count": 45,
            "confidence_score": 0.89,
            "last_updated": (now - timedelta(minutes=30)).isoformat().replace('+00:00', 'Z'),
            "can_refresh": False,
            "processing_time_ms": 2341
        }
    }
    print(json.dumps(example_response, indent=2))
    
    print("\n✅ Response Quality Indicators Implementation Complete!")
    print("📚 See RESPONSE_QUALITY_IMPLEMENTATION.md for full documentation\n")

if __name__ == "__main__":
    main()
