#!/usr/bin/env python3
"""
scripts/cleanup_gdelt_heuristic.py

Remove GDELT alerts identified as noise using heuristic quality signals.
Uses the same logic as assess_gdelt_heuristic_cleanup.py.
"""
import os
import sys
import re
import argparse
from datetime import datetime
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load production environment
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
production_env = os.path.join(project_root, '.env.production')

if not os.path.exists(production_env):
    print(f"ERROR: {production_env} not found")
    sys.exit(1)

load_dotenv(production_env, override=True)

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL or not DATABASE_URL.startswith('postgresql://'):
    print(f"ERROR: Invalid DATABASE_URL in .env.production")
    sys.exit(1)

print(f"✓ Connected to PostgreSQL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'database'}")
print()


def is_gdelt_noise(alert: Dict[str, Any]) -> tuple[bool, str]:
    """
    Identify GDELT noise based on signals in processed alert data.
    Returns: (is_noise, reason)
    """
    title = alert.get('title') or ''
    summary = alert.get('summary') or ''
    gpt_summary = alert.get('gpt_summary') or ''
    display_summary = gpt_summary or summary
    confidence = alert.get('confidence') or '0'
    score = alert.get('score') or '0'
    link = alert.get('link') or ''
    country = alert.get('country') or ''
    city = alert.get('city') or ''
    latitude = alert.get('latitude')
    longitude = alert.get('longitude')
    
    # Convert score/confidence to float
    try:
        score_val = float(score) if score else 0
    except (ValueError, TypeError):
        score_val = 0
    
    try:
        confidence_val = float(confidence) if confidence else 0
    except (ValueError, TypeError):
        confidence_val = 0
    
    # 1. Raw GDELT actor pair title pattern: "ACTOR1 → ACTOR2 (###)"
    if re.match(r'^[A-Z\s]+→.*\(\d+\)$', title, re.IGNORECASE):
        return True, 'actor_pair_title'
    
    # 2. Title starts with "GDELT:" prefix (never enriched)
    if title.startswith('GDELT:'):
        return True, 'gdelt_prefix'
    
    # 3. No meaningful summary
    if len(display_summary) < 20:
        return True, 'no_summary'
    
    # 4. Generic GDELT summary patterns (never enriched)
    gdelt_patterns = [
        'GDELT event:',
        'Goldstein:',
        'Tone:',
        'QuadClass:',
        'CAMEO:',
        'Global Event ID'
    ]
    if any(pattern in display_summary for pattern in gdelt_patterns):
        return True, 'gdelt_patterns'
    
    # 5. Very low confidence
    if confidence_val > 0 and confidence_val < 0.15:
        return True, 'low_confidence'
    
    # 6. No source URL (can't verify)
    if not link or not link.startswith('http'):
        return True, 'no_url'
    
    # 7. Title is location code only
    if len(title.strip()) <= 3 and title.isupper():
        return True, 'short_title'
    
    # 8. No location at all
    if not country and not city and latitude is None and longitude is None:
        return True, 'no_location'
    
    # 9. Score too low for display
    if score_val > 0 and score_val < 30:
        return True, 'low_score'
    
    # 10. Location mismatch heuristic
    title_lower = title.lower()
    location_lower = f"{city or ''} {country or ''}".lower()
    
    conflict_zones = {
        'ukrain': ['ukraine', 'kyiv', 'kharkiv', 'donetsk', 'lviv', 'crimea'],
        'russia': ['russia', 'moscow', 'st. petersburg', 'russian'],
        'israel': ['israel', 'tel aviv', 'jerusalem', 'israeli'],
        'gaza': ['gaza', 'palestine', 'palestinian'],
        'syria': ['syria', 'damascus', 'aleppo', 'syrian'],
        'yemen': ['yemen', 'sanaa', 'aden', 'yemeni'],
        'iran': ['iran', 'tehran', 'iranian'],
        'china': ['china', 'beijing', 'shanghai', 'chinese'],
        'india': ['india', 'delhi', 'mumbai', 'indian']
    }
    
    for keyword, valid_locations in conflict_zones.items():
        if keyword in title_lower:
            if location_lower and not any(loc in location_lower for loc in valid_locations):
                return True, 'location_mismatch'
    
    return False, 'signal'


def cleanup_gdelt_heuristic(dry_run=True, batch_size=1000):
    """Remove GDELT alerts identified as noise using heuristics"""
    
    print(f"{'=' * 70}")
    print(f"GDELT Heuristic Cleanup {'(DRY RUN - Safe Mode)' if dry_run else '(LIVE MODE)'}")
    print(f"{'=' * 70}\n")
    
    start_time = datetime.now()
    print(f"Started: {start_time}\n")
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Count total GDELT alerts
    cur.execute("SELECT COUNT(*) as count FROM alerts WHERE LOWER(source) = 'gdelt'")
    total_count = cur.fetchone()['count']
    
    print(f"Total GDELT alerts in database: {total_count:,}")
    
    if total_count == 0:
        print("No GDELT alerts found. Nothing to do.")
        cur.close()
        conn.close()
        return 0, 0
    
    print(f"Processing in batches of {batch_size}...\n")
    print(f"{'=' * 70}\n")
    
    noise_count = 0
    signal_count = 0
    offset = 0
    batch_num = 0
    
    noise_reasons = {}
    
    while True:
        # Fetch batch
        cur.execute("""
            SELECT 
                uuid, title, summary, gpt_summary, confidence, score,
                link, country, city, latitude, longitude
            FROM alerts
            WHERE LOWER(source) = 'gdelt'
            ORDER BY published DESC
            LIMIT %s OFFSET %s
        """, (batch_size, offset))
        
        alerts = cur.fetchall()
        if not alerts:
            break
        
        batch_num += 1
        batch_noise = 0
        batch_signal = 0
        delete_uuids = []
        
        for alert in alerts:
            is_noise, reason = is_gdelt_noise(alert)
            
            if is_noise:
                batch_noise += 1
                noise_count += 1
                delete_uuids.append(alert['uuid'])
                noise_reasons[reason] = noise_reasons.get(reason, 0) + 1
            else:
                batch_signal += 1
                signal_count += 1
        
        print(f"Batch {batch_num}: Processing {len(alerts)} alerts (offset {offset})")
        print(f"  Keep: {batch_signal}, Delete: {batch_noise}")
        
        # Execute batch deletion
        if delete_uuids:
            if not dry_run:
                delete_cur = conn.cursor()
                delete_cur.execute(
                    "DELETE FROM alerts WHERE uuid = ANY(%s) AND LOWER(source) = 'gdelt'",
                    (delete_uuids,)
                )
                deleted = delete_cur.rowcount
                conn.commit()
                delete_cur.close()
                print(f"  → Deleted {deleted} alerts")
            else:
                print(f"  → Would delete {batch_noise} alerts")
        
        progress_pct = ((offset + len(alerts)) / total_count * 100)
        print(f"  Progress: {offset + len(alerts):,}/{total_count:,} ({progress_pct:.1f}%)\n")
        
        offset += batch_size
    
    cur.close()
    conn.close()
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # Summary
    print(f"{'=' * 70}")
    print("Cleanup Summary")
    print(f"{'=' * 70}")
    print(f"Total GDELT alerts processed: {total_count:,}")
    print(f"Kept (signal): {signal_count:,} ({(signal_count/total_count*100):.1f}%)")
    print(f"Deleted (noise): {noise_count:,} ({(noise_count/total_count*100):.1f}%)")
    print(f"Duration: {duration:.1f} seconds")
    print(f"Finished: {end_time}")
    
    if noise_reasons:
        print(f"\nNoise breakdown:")
        for reason, count in sorted(noise_reasons.items(), key=lambda x: x[1], reverse=True):
            pct = (count / noise_count * 100) if noise_count > 0 else 0
            print(f"  {reason:20s}: {count:5,} ({pct:5.1f}%)")
    
    if dry_run:
        print(f"\n{'⚠' * 35}")
        print(f"⚠  THIS WAS A DRY RUN - NO DATA WAS DELETED  ⚠")
        print(f"{'⚠' * 35}\n")
        print("To execute cleanup for real, run:")
        print("  python scripts/cleanup_gdelt_heuristic.py --live")
    else:
        print("\n✅ Cleanup completed successfully!")
        print("\nNext steps:")
        print("1. Run VACUUM to reclaim disk space:")
        print("   python vacuum_only.py")
        print("\n2. Deploy new filtering code to prevent future noise:")
        print("   git add . && git commit -m 'GDELT filtering' && git push")
    
    return noise_count, signal_count


def main():
    parser = argparse.ArgumentParser(
        description='Remove GDELT alerts identified as noise using heuristics'
    )
    parser.add_argument(
        '--live',
        action='store_true',
        help='Execute deletion (default is dry-run)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for processing (default: 1000)'
    )
    
    args = parser.parse_args()
    
    try:
        cleanup_gdelt_heuristic(dry_run=not args.live, batch_size=args.batch_size)
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
