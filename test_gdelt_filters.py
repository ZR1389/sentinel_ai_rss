#!/usr/bin/env python3
"""
Test GDELT filters with sample events
"""
import sys
sys.path.insert(0, '.')

from gdelt_filters import should_ingest_gdelt_event, get_filter_stats

# Sample test events
test_events = [
    {
        "name": "High-signal armed conflict",
        "event": {
            "global_event_id": 1001,
            "sql_date": 20251119,
            "event_code": "190",  # Use conventional military force
            "quad_class": 4,  # Material conflict
            "goldstein": -8.5,
            "num_mentions": 15,
            "avg_tone": -12.3,
            "action_lat": 35.5,
            "action_long": 45.2,
            "action_country": "SY"
        },
        "expect": True
    },
    {
        "name": "Violent protest",
        "event": {
            "global_event_id": 1002,
            "sql_date": 20251119,
            "event_code": "145",  # Protest violently
            "quad_class": 2,  # Verbal conflict
            "goldstein": -6.0,
            "num_mentions": 8,
            "avg_tone": -8.5,
            "action_lat": 48.8,
            "action_long": 2.3,
            "action_country": "FR"
        },
        "expect": True
    },
    {
        "name": "Diplomatic cooperation (should reject)",
        "event": {
            "global_event_id": 1003,
            "sql_date": 20251119,
            "event_code": "036",  # Express intent to cooperate
            "quad_class": 1,  # Verbal cooperation
            "goldstein": 4.0,
            "num_mentions": 10,
            "avg_tone": 3.5,
            "action_lat": 40.7,
            "action_long": -74.0,
            "action_country": "US"
        },
        "expect": False
    },
    {
        "name": "Low goldstein (should reject)",
        "event": {
            "global_event_id": 1004,
            "sql_date": 20251119,
            "event_code": "190",
            "quad_class": 4,
            "goldstein": -2.0,  # Not negative enough
            "num_mentions": 10,
            "avg_tone": -8.0,
            "action_lat": 35.5,
            "action_long": 45.2,
            "action_country": "SY"
        },
        "expect": False
    },
    {
        "name": "Low mentions (should reject)",
        "event": {
            "global_event_id": 1005,
            "sql_date": 20251119,
            "event_code": "190",
            "quad_class": 4,
            "goldstein": -8.0,
            "num_mentions": 1,  # Only 1 source
            "avg_tone": -10.0,
            "action_lat": 35.5,
            "action_long": 45.2,
            "action_country": "SY"
        },
        "expect": False
    },
    {
        "name": "Missing coordinates (should reject)",
        "event": {
            "global_event_id": 1006,
            "sql_date": 20251119,
            "event_code": "190",
            "quad_class": 4,
            "goldstein": -8.0,
            "num_mentions": 10,
            "avg_tone": -10.0,
            "action_lat": None,
            "action_long": None,
            "action_country": "SY"
        },
        "expect": False
    },
    {
        "name": "(0,0) coordinates (should reject)",
        "event": {
            "global_event_id": 1007,
            "sql_date": 20251119,
            "event_code": "190",
            "quad_class": 4,
            "goldstein": -8.0,
            "num_mentions": 10,
            "avg_tone": -10.0,
            "action_lat": 0.0,
            "action_long": 0.0,
            "action_country": "SY"
        },
        "expect": False  # (0,0) is invalid location data
    },
    {
        "name": "Wrong event code (should reject)",
        "event": {
            "global_event_id": 1008,
            "sql_date": 20251119,
            "event_code": "010",  # Make statement (not conflict)
            "quad_class": 2,
            "goldstein": -6.0,
            "num_mentions": 10,
            "avg_tone": -8.0,
            "action_lat": 35.5,
            "action_long": 45.2,
            "action_country": "SY"
        },
        "expect": False
    }
]

def main():
    print("=" * 70)
    print("GDELT Filter Validation")
    print("=" * 70)
    
    # Show configuration
    config = get_filter_stats()
    print("\nFilter Configuration:")
    for key, value in config.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 70)
    print("Running Test Cases")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    for test in test_events:
        name = test["name"]
        event = test["event"]
        expect = test["expect"]
        
        result = should_ingest_gdelt_event(event, stage="ingest")
        status = "✓ PASS" if result == expect else "✗ FAIL"
        
        if result == expect:
            passed += 1
        else:
            failed += 1
        
        print(f"\n{status}: {name}")
        print(f"  Event ID: {event['global_event_id']}")
        print(f"  Code: {event['event_code']}, Quad: {event['quad_class']}")
        print(f"  Goldstein: {event['goldstein']}, Mentions: {event['num_mentions']}, Tone: {event['avg_tone']}")
        print(f"  Coords: ({event.get('action_lat')}, {event.get('action_long')})")
        print(f"  Expected: {expect}, Got: {result}")
    
    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\n✓ All tests passed!")

if __name__ == "__main__":
    main()
