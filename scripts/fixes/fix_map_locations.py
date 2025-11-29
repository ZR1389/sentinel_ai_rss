#!/usr/bin/env python3
"""
fix_map_locations.py - Re-extract precise locations for alerts with weak geocoding

Targets alerts with:
- country_centroid (too generic for zoom-in)
- legacy_precise (backfilled, may be inaccurate)
- low confidence methods

Re-runs location extraction using the full location service stack.
"""

import sys
from db_utils import _get_db_connection
from psycopg2.extras import RealDictCursor

def fix_alert_locations(dry_run=True):
    """Re-extract locations for alerts with weak geocoding."""
    
    print("\n" + "="*70)
    print("FIXING MAP ALERT LOCATIONS")
    print("="*70)
    
    # Import location service
    try:
        from services.location_service_consolidated import detect_location
    except ImportError:
        print("✗ location_service_consolidated not available")
        return 1
    
    weak_methods = ['country_centroid', 'legacy_precise', 'low', 'moderate']
    
    with _get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get alerts with weak location methods
            cur.execute("""
                SELECT uuid, title, summary, country, city, 
                       latitude, longitude, location_method
                FROM alerts
                WHERE location_method = ANY(%s)
                  AND (title IS NOT NULL OR summary IS NOT NULL)
                ORDER BY published DESC
                LIMIT 500
            """, (weak_methods,))
            
            alerts = cur.fetchall()
            print(f"\nFound {len(alerts)} alerts with weak location methods")
            
            if not alerts:
                print("✓ No alerts need location fixes")
                return 0
            
            if dry_run:
                print("\n📊 Sample alerts to fix:")
                for i, alert in enumerate(alerts[:10], 1):
                    print(f"\n{i}. {alert['title'][:60]}")
                    print(f"   Current: {alert['city'] or 'N/A'}, {alert['country'] or 'N/A'}")
                    print(f"   Method: {alert['location_method']}")
                    print(f"   Coords: {alert['latitude']}, {alert['longitude']}")
                
                print(f"\n... and {len(alerts) - 10} more" if len(alerts) > 10 else "")
                print("\n" + "="*70)
                print("DRY RUN - No changes made")
                print("="*70)
                print(f"\nTo fix these {len(alerts)} alerts, run:")
                print("    python fix_map_locations.py --execute")
                return 0
            
            # Execute fixes
            fixed_count = 0
            failed_count = 0
            
            for alert in alerts:
                try:
                    # Combine title and summary for better context
                    text = f"{alert['title'] or ''} {alert['summary'] or ''}".strip()
                    
                    if not text or len(text) < 20:
                        failed_count += 1
                        continue
                    
                    # Re-extract location
                    result = detect_location(text)
                    
                    if result.city or result.country:
                        # Update alert with new location
                        update_fields = []
                        update_params = []
                        
                        if result.city:
                            update_fields.append("city = %s")
                            update_params.append(result.city)
                        
                        if result.country:
                            update_fields.append("country = %s")
                            update_params.append(result.country)
                        
                        if result.latitude and result.longitude:
                            update_fields.append("latitude = %s")
                            update_fields.append("longitude = %s")
                            update_params.extend([result.latitude, result.longitude])
                        
                        if result.method:
                            update_fields.append("location_method = %s")
                            update_params.append(result.method)
                        
                        if result.confidence:
                            update_fields.append("location_confidence = %s")
                            update_params.append(result.confidence)
                        
                        if update_fields:
                            update_params.append(alert['uuid'])
                            
                            cur.execute(f"""
                                UPDATE alerts
                                SET {', '.join(update_fields)}
                                WHERE uuid = %s
                            """, tuple(update_params))
                            
                            fixed_count += 1
                            
                            if fixed_count % 50 == 0:
                                print(f"  Progress: {fixed_count}/{len(alerts)} alerts fixed...")
                                conn.commit()
                    else:
                        failed_count += 1
                
                except Exception as e:
                    print(f"  ✗ Error fixing alert {alert['uuid']}: {e}")
                    failed_count += 1
            
            conn.commit()
            
            print("\n" + "="*70)
            print("LOCATION FIX COMPLETE")
            print("="*70)
            print(f"\n✓ Fixed: {fixed_count}")
            print(f"✗ Failed: {failed_count}")
            print(f"\nAlerts now have more precise locations for map zoom.")
            
            return 0

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Fix weak alert locations for map display")
    parser.add_argument('--dry-run', action='store_true', help='Preview without making changes')
    parser.add_argument('--execute', action='store_true', help='Actually fix the locations')
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        print("Error: Must specify either --dry-run or --execute")
        parser.print_help()
        return 1
    
    if args.dry_run and args.execute:
        print("Error: Cannot specify both --dry-run and --execute")
        return 1
    
    try:
        return fix_alert_locations(dry_run=args.dry_run)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
