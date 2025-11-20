#!/usr/bin/env python3
"""
scripts/assess_gdelt_heuristic_cleanup.py

Assess GDELT alert quality using heuristics on processed alert data.
No need for original GDELT metadata - use quality signals from enriched alerts.
"""
import os
import sys
import re
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
    No need for original GDELT metadata.
    
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
    
    # Convert score/confidence to float (they might be strings)
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
    
    # 7. Title is location code only (e.g., "UP", "IN", "RU")
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
                # Title mentions Ukraine but location is India → likely mismatch
                return True, 'location_mismatch'
    
    # Passed all noise checks
    return False, 'signal'


def assess_heuristic_cleanup():
    """Assess cleanup using heuristics on processed alerts"""
    
    print(f"{'=' * 70}")
    print("GDELT Heuristic Assessment")
    print(f"{'=' * 70}\n")
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Fetch all GDELT alerts
    cur.execute("""
        SELECT 
            uuid, title, summary, gpt_summary, confidence, score, 
            link, country, city, latitude, longitude, published
        FROM alerts
        WHERE LOWER(source) = 'gdelt'
        ORDER BY published DESC
    """)
    
    alerts = cur.fetchall()
    total = len(alerts)
    
    print(f"Total GDELT alerts: {total:,}")
    print("Analyzing quality signals...\n")
    
    noise_count = 0
    signal_count = 0
    noise_reasons = {}
    
    noise_samples = []
    signal_samples = []
    
    for alert in alerts:
        is_noise, reason = is_gdelt_noise(alert)
        
        if is_noise:
            noise_count += 1
            noise_reasons[reason] = noise_reasons.get(reason, 0) + 1
            if len(noise_samples) < 5:
                noise_samples.append(alert)
        else:
            signal_count += 1
            if len(signal_samples) < 5:
                signal_samples.append(alert)
    
    # Results
    signal_pct = (signal_count / total * 100) if total > 0 else 0
    noise_pct = (noise_count / total * 100) if total > 0 else 0
    
    print(f"{'=' * 70}")
    print(f"Signal (KEEP):   {signal_count:,} ({signal_pct:.1f}%)")
    print(f"Noise (DELETE):  {noise_count:,} ({noise_pct:.1f}%)")
    print(f"{'=' * 70}\n")
    
    if noise_reasons:
        print("Noise breakdown:")
        for reason, count in sorted(noise_reasons.items(), key=lambda x: x[1], reverse=True):
            pct = (count / noise_count * 100) if noise_count > 0 else 0
            print(f"  {reason:20s}: {count:5,} ({pct:5.1f}%)")
    
    # Show samples
    if noise_samples:
        print(f"\nSample alerts to DELETE (first {len(noise_samples)}):")
        for alert in noise_samples:
            title = (alert['title'] or '')[:60]
            location = f"{alert['city'] or 'N/A'}, {alert['country'] or 'N/A'}"
            score = alert['score'] or 'N/A'
            is_noise, reason = is_gdelt_noise(alert)
            print(f"  ✗ {title}... | {location} | Score: {score} | Reason: {reason}")
    
    if signal_samples:
        print(f"\nSample alerts to KEEP (first {len(signal_samples)}):")
        for alert in signal_samples:
            title = (alert['title'] or '')[:60]
            location = f"{alert['city'] or 'N/A'}, {alert['country'] or 'N/A'}"
            score = alert['score'] or 'N/A'
            print(f"  ✓ {title}... | {location} | Score: {score}")
    
    cur.close()
    conn.close()
    
    # Recommendation
    print(f"\n{'=' * 70}")
    print("Recommendation")
    print(f"{'=' * 70}")
    
    if noise_pct > 80:
        print("✓ Heuristic cleanup HIGHLY recommended - majority is noise")
        print(f"  This will remove {noise_count:,} alerts ({noise_pct:.1f}%)")
        print("  Run: python scripts/cleanup_gdelt_heuristic.py --live")
    elif noise_pct > 50:
        print("✓ Heuristic cleanup recommended - more noise than signal")
        print(f"  This will remove {noise_count:,} alerts ({noise_pct:.1f}%)")
        print("  Run: python scripts/cleanup_gdelt_heuristic.py --live")
    elif noise_pct > 20:
        print("⚠ Moderate noise detected - consider selective cleanup")
        print(f"  This would remove {noise_count:,} alerts ({noise_pct:.1f}%)")
        print("  Run: python scripts/cleanup_gdelt_heuristic.py --live")
    else:
        print("⚠ Less than 20% noise detected")
        print("  Most alerts appear legitimate based on heuristics")
        print("  Consider Option 2 (keep all) or manually review samples")
    
    return noise_count, signal_count


if __name__ == '__main__':
    try:
        noise, signal = assess_heuristic_cleanup()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
