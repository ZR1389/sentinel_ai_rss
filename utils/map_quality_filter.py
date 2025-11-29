"""map_quality_filter.py

Quality gating for map display: only show alerts with reliable geocoding.

PROBLEM: Alerts without proper coordinates pollute the map with:
- Country centroids (imprecise, not actual event location)
- Low-confidence guesses (wrong cities)
- Missing coordinates (unusable for proximity/map features)

SOLUTION: Filter alerts based on location_method quality tiers.

Quality tiers:
  TIER 1 (display on map): coordinates, nlp_nominatim, nlp_opencage, moderate
  TIER 2 (suppressed): country_centroid, low confidence methods
  TIER 3 (suppressed): unknown, missing coords

Usage in queries:
  # Standard map query (quality gated)
  SELECT * FROM alerts WHERE latitude IS NOT NULL 
    AND location_method IN ('coordinates', 'nlp_nominatim', 'nlp_opencage', 'moderate', 'production_stack')
  
  # Admin view (show all including low quality)
  SELECT * FROM alerts WHERE latitude IS NOT NULL  # no filter
  
  # Function helper
  from map_quality_filter import is_displayable_on_map
  if is_displayable_on_map(alert):
      render_on_map(alert)
"""
from typing import Dict, Any, Optional

# Tier 1: High quality - display on map
HIGH_QUALITY_METHODS = {
    'coordinates',          # Original RSS coordinates
    'nlp_nominatim',        # NLP extraction + Nominatim geocoding
    'nlp_opencage',         # NLP extraction + OpenCage geocoding  
    'production_stack',     # Full production geocoding stack
    'nominatim',            # Direct Nominatim geocoding
    'opencage',             # Direct OpenCage geocoding
    'db_cache',             # Database cache hit (pre-validated)
    'legacy_precise',       # Legacy city-level coordinates (re-classified from unknown)
    'moderate',             # Moderate confidence extraction
}

# Tier 2: Medium quality - country-level fallback (suppress for city-level maps)
MEDIUM_QUALITY_METHODS = {
    'country_centroid',     # Fallback to country center
}

# Tier 3: Low quality - no coordinates or failed extraction (always suppress)
LOW_QUALITY_METHODS = {
    'unknown',
    'low',
}

def is_displayable_on_map(alert: Dict[str, Any], strict: bool = True) -> bool:
    """
    Check if alert should be displayed on map based on geocoding quality.
    
    Args:
        alert: Alert dictionary with latitude, longitude, location_method
        strict: If True, only show Tier 1 (high quality). If False, include Tier 2 (country centroids)
    
    Returns:
        True if alert should be displayed on map
    """
    # Must have coordinates
    if not alert.get('latitude') or not alert.get('longitude'):
        return False
    
    method = alert.get('location_method', 'unknown')
    
    # Tier 1: Always display
    if method in HIGH_QUALITY_METHODS:
        return True
    
    # Tier 2: Display only if not strict
    if method in MEDIUM_QUALITY_METHODS:
        return not strict
    
    # Tier 3: Never display
    return False

def get_map_quality_sql_filter(strict: bool = True, table_alias: str = 'a') -> str:
    """
    Generate SQL WHERE clause for map quality filtering.
    
    Args:
        strict: If True, only Tier 1. If False, include Tier 2.
        table_alias: Table alias to use in query (default 'a')
    
    Returns:
        SQL WHERE clause string
    """
    if strict:
        methods = HIGH_QUALITY_METHODS
    else:
        methods = HIGH_QUALITY_METHODS | MEDIUM_QUALITY_METHODS
    
    # Build SQL IN clause
    methods_list = "', '".join(methods)
    return f"{table_alias}.latitude IS NOT NULL AND {table_alias}.longitude IS NOT NULL AND {table_alias}.location_method IN ('{methods_list}')"

def get_quality_stats(cursor) -> Dict[str, int]:
    """
    Get count of alerts by quality tier.
    
    Args:
        cursor: Database cursor
    
    Returns:
        Dict with counts per tier
    """
    cursor.execute("""
        SELECT 
            location_method,
            COUNT(*) as count,
            SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) as with_coords
        FROM alerts
        GROUP BY location_method
    """)
    
    rows = cursor.fetchall()
    
    tier1 = 0
    tier2 = 0
    tier3 = 0
    
    for row in rows:
        method = row[0] or 'unknown'
        count_with_coords = row[2]
        
        if method in HIGH_QUALITY_METHODS:
            tier1 += count_with_coords
        elif method in MEDIUM_QUALITY_METHODS:
            tier2 += count_with_coords
        else:
            tier3 += count_with_coords
    
    return {
        'tier1_high_quality': tier1,
        'tier2_medium_quality': tier2,
        'tier3_low_quality': tier3,
        'displayable_strict': tier1,
        'displayable_permissive': tier1 + tier2,
    }

# Example usage in API endpoint
def example_map_query():
    """
    Example of using quality filter in map API endpoint.
    """
    from db_utils import _get_db_connection
    
    with _get_db_connection() as conn:
        cur = conn.cursor()
        
        # Strict mode: only high-quality coordinates
        sql_filter = get_map_quality_sql_filter(strict=True, table_alias='a')
        
        query = f"""
            SELECT id, title, latitude, longitude, city, country, score, category
            FROM alerts a
            WHERE {sql_filter}
              AND score >= 50
              AND published >= NOW() - INTERVAL '30 days'
            ORDER BY published DESC
            LIMIT 1000
        """
        
        cur.execute(query)
        alerts = cur.fetchall()
        
        # These alerts are safe to display on map
        return alerts

if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/home/zika/sentinel_ai_rss')
    from dotenv import load_dotenv
    import os
    load_dotenv('.env.production', override=True)
    
    from db_utils import _get_db_connection
    
    with _get_db_connection() as conn:
        cur = conn.cursor()
        stats = get_quality_stats(cur)
        
        print("=== Map Quality Gating Stats ===\n")
        print(f"Tier 1 (High Quality):    {stats['tier1_high_quality']:4d} alerts - DISPLAY ON MAP")
        print(f"Tier 2 (Medium Quality):  {stats['tier2_medium_quality']:4d} alerts - country centroids (optional)")
        print(f"Tier 3 (Low Quality):     {stats['tier3_low_quality']:4d} alerts - SUPPRESS\n")
        print(f"Displayable (strict):     {stats['displayable_strict']:4d} alerts")
        print(f"Displayable (permissive): {stats['displayable_permissive']:4d} alerts")
        
        total = stats['tier1_high_quality'] + stats['tier2_medium_quality'] + stats['tier3_low_quality']
        if total > 0:
            display_pct = (stats['displayable_strict'] / total * 100)
            print(f"\nQuality rate: {display_pct:.1f}% of coordinates are map-displayable")
