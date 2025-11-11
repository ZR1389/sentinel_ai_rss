#!/usr/bin/env python3
"""
Final integration test demonstrating the enhanced advisor with city_utils integration
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from advisor import _validate_location_match

def test_real_world_scenarios():
    """Test real-world advisor scenarios with enhanced location processing"""
    
    print("=== Real-World Advisor Test with Enhanced Location Processing ===\n")
    
    # Mock alert data simulating various geographic scenarios
    test_scenarios = [
        {
            "name": "Perfect City Match - Amsterdam",
            "query": "I'm traveling to Amsterdam next week for a business conference. What security precautions should I take?",
            "alerts": [
                {
                    "title": "Increased Pickpocketing in Amsterdam Tourist Areas",
                    "description": "Police report surge in pickpocketing incidents around Central Station",
                    "location_data": {"city": "Amsterdam", "country": "Netherlands", "region": "North Holland"},
                    "severity": "Medium",
                    "incident_count_30d": 8
                }
            ]
        },
        {
            "name": "Country-Level Query - Japan",
            "query": "General security advice for Japan travel",
            "alerts": [
                {
                    "title": "Tokyo Subway Security Updates",
                    "description": "Enhanced security measures on JR lines",
                    "location_data": {"city": "Tokyo", "country": "Japan", "region": "Kantō"},
                    "severity": "Low", 
                    "incident_count_30d": 12
                }
            ]
        }
    ]
    
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"--- Scenario {i}: {scenario['name']} ---")
        print(f"Query: {scenario['query']}")
        print(f"Alert data: {len(scenario['alerts'])} alerts")
        
        try:
            # Test the location validation directly
            for alert in scenario['alerts']:
                score, matched_name, warning = _validate_location_match(
                    scenario['query'], 
                    alert['location_data']
                )
                
                print(f"  📍 Location match score: {score:.1f}")
                print(f"  📍 Matched location: {matched_name}")
                if warning:
                    print(f"  ⚠️ Warning: {warning}")
                
                # Assess the quality
                if score >= 70:
                    print(f"  ✅ Strong location match - advisor will provide specific recommendations")
                elif score >= 30:
                    print(f"  🟡 Partial location match - advisor will provide general guidance")
                else:
                    print(f"  ❌ Poor location match - advisor will provide generic safety advice only")
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
        
        print()
    
    print("=== city_utils Enhanced Features Demonstration ===")
    
    # Show the enhanced features in action
    from city_utils import fuzzy_match_city, normalize_city_country
    
    test_queries = [
        "Security concerns for my trip to New York City",
        "What about safety in london england?", 
        "Paris France travel advisory needed",
        "Berlin safety information"
    ]
    
    for query in test_queries:
        print(f"Query: '{query}'")
        
        # Extract city using fuzzy matching
        city_match = fuzzy_match_city(query)
        print(f"  🏙️ Extracted city: {city_match}")
        
        # Normalize the result
        norm_city, norm_country = normalize_city_country(city_match or query.split()[-1])
        print(f"  🌍 Normalized: {norm_city}, {norm_country}")
        print()

if __name__ == "__main__":
    test_real_world_scenarios()
