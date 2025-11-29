#!/usr/bin/env python3
"""
clean_non_english_alerts.py - Remove non-English alerts from database

Identifies and removes alerts that are:
1. Not in English (using language detection)
2. From removed non-English RSS feeds
3. Sports/entertainment noise that slipped through

Usage:
    python clean_non_english_alerts.py --dry-run    # Preview what would be deleted
    python clean_non_english_alerts.py --execute    # Actually delete the alerts
"""

import sys
import argparse
from datetime import datetime
from typing import List, Dict, Any

def detect_language_safe(text: str) -> str:
    """Safely detect language of text."""
    try:
        from langdetect import detect
        if not text or len(text.strip()) < 20:
            return "unknown"
        return detect(text[:500])
    except Exception:
        return "unknown"

def check_sports_keywords(text: str) -> bool:
    """Check if text contains obvious sports keywords."""
    text_lower = text.lower()
    
    sports_indicators = [
        # Scores
        r"\d+-\d+", r"\d+:\d+",
        # Keywords
        "vs ", " vs.", "versus",
        "championship", "tournament", "league", "playoff",
        "goal", "scored", "match", "game",
        "uefa", "fifa", "nba", "nfl", "mlb",
        "champion", "trophy", "award",
        "stadium", "arena"
    ]
    
    import re
    for pattern in sports_indicators:
        if re.search(pattern, text_lower):
            return True
    
    return False

def identify_non_english_alerts(dry_run: bool = True) -> List[Dict[str, Any]]:
    """Identify alerts that should be removed - optimized version."""
    from db_utils import _get_db_connection
    from psycopg2.extras import RealDictCursor
    
    print("\n" + "="*70)
    print("SCANNING ALERTS FOR NON-ENGLISH CONTENT")
    print("="*70)
    
    # Removed feed domains to check
    removed_domains = [
        'novosti.rs', 'lemonde.fr', 'romatoday.it', 'clarin.com',
        'hurriyet.com', 'ansa.it', 'ahram.org', 'tehrantimes.com',
        'okaz.com.sa', 'eltiempo.com', 'elcomercio.pe', 'latercera.com',
        'nzz.ch', 'derstandard.at', 'parool.nl', 'aftenposten.no',
        'hs.fi', 'dr.dk', 'sme.sk', 'bursa.ro', 'stolica.bg',
        'plovdiv24.bg', 'athensvoice.gr', 'spbdnevnik.ru', 'rbc.ru',
        'lbcgroup.tv', 'sana.sy', 'rcnradio.com', 'fratmat.info',
        'beninwebtv.com', 'radiookapi.net', 'quebechebdo.com',
        'aps.dz', 'eluniversal.com', 'g1.globo.com', 'themoscowtimes.com'
    ]
    
    to_remove = []
    
    with _get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get ALL alerts - we'll analyze them for actual language
            # Don't trust the language field since it was incorrectly set to 'en'
            cur.execute("""
                SELECT uuid, title, summary, source, published
                FROM alerts
                ORDER BY published DESC
            """)
            
            all_alerts = cur.fetchall()
            print(f"\nTotal alerts in database: {len(all_alerts)}")
            
            non_english_count = 0
            sports_count = 0
            removed_source_count = 0
            
            # Analyze each alert
            for alert in all_alerts:
                reasons = []
                title = alert.get('title', '') or ''
                source = (alert.get('source') or '').lower()
                
                # Check 1: Source from removed feed (highest priority)
                is_removed_source = False
                for domain in removed_domains:
                    if domain in source:
                        reasons.append(f"removed_source={domain}")
                        is_removed_source = True
                        removed_source_count += 1
                        break
                
                # Check 2: Detect actual language from title
                if title and len(title) > 20:
                    detected_lang = detect_language_safe(title)
                    if detected_lang not in ['en', 'unknown']:
                        reasons.append(f"detected={detected_lang}")
                        non_english_count += 1
                
                # Check 3: Sports keywords in title
                if check_sports_keywords(title):
                    reasons.append("sports_keywords")
                    sports_count += 1
                
                if reasons:
                    to_remove.append({
                        'uuid': alert['uuid'],
                        'title': title[:80] if title else 'No title',
                        'source': alert.get('source', 'unknown'),
                        'published': alert.get('published'),
                        'reasons': reasons
                    })
            
            print(f"\n📊 Analysis Results:")
            print(f"   From removed sources: {removed_source_count}")
            print(f"   Non-English detected: {non_english_count}")
            print(f"   Sports keywords: {sports_count}")
            print(f"   Total to remove: {len(to_remove)}")
    
    return to_remove

def display_removal_preview(alerts: List[Dict[str, Any]], limit: int = 20):
    """Display preview of alerts to be removed."""
    print("\n" + "="*70)
    print(f"PREVIEW: First {min(limit, len(alerts))} alerts to be removed")
    print("="*70)
    
    for i, alert in enumerate(alerts[:limit], 1):
        print(f"\n{i}. UUID: {alert['uuid']}")
        print(f"   Title: {alert['title']}")
        print(f"   Source: {alert['source']}")
        print(f"   Published: {alert['published']}")
        print(f"   Reasons: {', '.join(alert['reasons'])}")
    
    if len(alerts) > limit:
        print(f"\n... and {len(alerts) - limit} more alerts")

def execute_cleanup(alerts: List[Dict[str, Any]]) -> int:
    """Actually delete the identified alerts."""
    from db_utils import _get_db_connection
    
    print("\n" + "="*70)
    print("EXECUTING CLEANUP")
    print("="*70)
    
    if not alerts:
        print("\n✓ No alerts to remove")
        return 0
    
    uuids = [a['uuid'] for a in alerts]
    
    with _get_db_connection() as conn:
        with conn.cursor() as cur:
            # Delete alerts
            cur.execute("""
                DELETE FROM alerts
                WHERE uuid = ANY(%s)
            """, (uuids,))
            
            deleted_count = cur.rowcount
            conn.commit()
            
            print(f"\n✓ Deleted {deleted_count} alerts")
    
    return deleted_count

def main():
    parser = argparse.ArgumentParser(
        description="Clean non-English alerts from database"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be deleted without actually deleting'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually delete the identified alerts'
    )
    parser.add_argument(
        '--preview-limit',
        type=int,
        default=20,
        help='Number of alerts to show in preview (default: 20)'
    )
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        print("Error: Must specify either --dry-run or --execute")
        parser.print_help()
        return 1
    
    if args.dry_run and args.execute:
        print("Error: Cannot specify both --dry-run and --execute")
        return 1
    
    try:
        # Identify alerts to remove
        alerts_to_remove = identify_non_english_alerts(dry_run=args.dry_run)
        
        if not alerts_to_remove:
            print("\n✓ No non-English alerts found. Database is clean!")
            return 0
        
        # Show preview
        display_removal_preview(alerts_to_remove, limit=args.preview_limit)
        
        if args.dry_run:
            print("\n" + "="*70)
            print("DRY RUN - No changes made")
            print("="*70)
            print(f"\nTo actually remove these {len(alerts_to_remove)} alerts, run:")
            print("    python clean_non_english_alerts.py --execute")
            return 0
        
        if args.execute:
            # Confirm before deleting
            print(f"\n⚠️  WARNING: About to delete {len(alerts_to_remove)} alerts")
            response = input("Type 'yes' to confirm: ")
            
            if response.lower() != 'yes':
                print("\n✗ Cleanup cancelled")
                return 1
            
            deleted = execute_cleanup(alerts_to_remove)
            
            print("\n" + "="*70)
            print("CLEANUP COMPLETE")
            print("="*70)
            print(f"\n✓ Removed {deleted} non-English alerts")
            print(f"\nDatabase is now focused on English-language intelligence.")
            
            return 0
    
    except Exception as e:
        print(f"\n✗ Error during cleanup: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
