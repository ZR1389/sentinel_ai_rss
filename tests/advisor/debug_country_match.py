#!/usr/bin/env python3
"""
Debug script for the country matching issue
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from city_utils import fuzzy_match_city, normalize_city_country, get_country_for_city

def debug_country_matching():
    print("=== Debugging Country Matching ===\n")
    
    query = "France"
    alert_data = {"city": "Lyon", "country": "France", "region": "Auvergne-Rhône-Alpes"}
    
    print(f"Query: '{query}'")
    print(f"Alert data: {alert_data}")
    print()
    
    # Test fuzzy matching
    query_city_match = fuzzy_match_city(query)
    print(f"fuzzy_match_city('{query}') = {query_city_match}")
    
    # Test normalization
    normalized_query_city, _ = normalize_city_country(query_city_match or query)
    print(f"normalize_city_country('{query_city_match or query}') = ({normalized_query_city}, _)")
    
    alert_city = (alert_data.get("city") or "").strip()
    alert_country = (alert_data.get("country") or "").strip()
    alert_region = (alert_data.get("region") or "").strip()
    
    normalized_alert_city, normalized_alert_country = normalize_city_country(alert_city, alert_country)
    print(f"normalize_city_country('{alert_city}', '{alert_country}') = ({normalized_alert_city}, {normalized_alert_country})")
    
    query_normalized = (normalized_query_city or "").lower()
    alert_country_norm = (normalized_alert_country or "").lower()
    
    print(f"query_normalized = '{query_normalized}'")
    print(f"alert_country_norm = '{alert_country_norm}'")
    
    print(f"query_normalized == alert_country_norm: {query_normalized == alert_country_norm}")
    print(f"query_normalized in alert_country_norm: {query_normalized in alert_country_norm}")
    print(f"alert_country_norm in query_normalized: {alert_country_norm in query_normalized}")

if __name__ == "__main__":
    debug_country_matching()
