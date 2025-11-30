#!/usr/bin/env python3
"""
Cleanup low-quality alerts (sports, entertainment, routine politics) from database.

Uses same noise detection logic as threat_scorer.py to identify and remove:
- Sports content (win, beat, championship, grand prix, etc.)
- Entertainment (movie, actor, music video, streaming, etc.)
- Routine politics (election, vote, appointed, first to wed, visit, etc.)
- Cultural events (pope, mosque, festival, pilgrimage, etc.)
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import unicodedata

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def get_db_connection():
    """Get database connection from environment variable."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    return psycopg2.connect(db_url)

def _strip_accents(s: str) -> str:
    """Remove accents from text."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

def _norm(text: str) -> str:
    """Normalize text: lowercase, strip accents, collapse whitespace."""
    return re.sub(r"\s+", " ", _strip_accents(text or "").lower()).strip()

# Noise detection patterns (from threat_scorer.py)
SPORTS_TERMS = [
    "win", "wins", "won", "beat", "beats", "score", "scored", "scores", "goal", "goals",
    "match", "game", "championship", "tournament", "league", "cup", "trophy",
    "football", "soccer", "basketball", "baseball", "cricket", "tennis", "rugby",
    "grand prix", "formula 1", "f1", "racing", "race", "nascar",
    "world cup", "olympics", "olympic", "medal", "gold medal", "silver medal",
    "team", "player", "coach", "season", "playoff", "playoffs", "final", "finals",
    "vs ", "versus", "defeat", "defeated", "victory"
]

ENTERTAINMENT_TERMS = [
    "movie", "film", "actor", "actress", "celebrity", "star", "music video",
    "album", "song", "concert", "performance", "show", "series", "episode",
    "grammy", "oscar", "emmy", "award", "nominee", "nomination",
    "box office", "premiere", "streaming", "netflix", "disney", "hbo",
    "band", "singer", "musician", "artist", "festival", "tour"
]

POLITICAL_ROUTINE_TERMS = [
    "election", "vote", "voting", "ballot", "campaign", "candidate",
    "minister appointed", "appointed as", "sworn in", "takes office",
    "prime minister", "president elected", "wins election",
    "cabinet reshuffle", "cabinet appointment", "ministry",
    "parliament", "senate", "congress", "legislature",
    "first to wed", "wedding", "married", "marriage", "ceremony",
    "visit", "visits", "visited", "met with", "meeting with", "summit"
]

CULTURAL_RELIGIOUS_TERMS = [
    "pope", "vatican", "mosque", "church", "temple", "cathedral",
    "religious ceremony", "pilgrimage", "prayer", "blessing", "mass",
    "festival", "celebration", "anniversary", "commemoration"
]

def detect_noise_content(title: str, summary: str) -> tuple:
    """
    Detect low-quality non-threat content.
    Returns (is_noise, noise_type, reason).
    """
    title_norm = _norm(title or "")
    summary_norm = _norm(summary or "")
    combined = f"{title_norm} {summary_norm}"
    
    # Sports detection
    sports_hits = sum(1 for term in SPORTS_TERMS if term in combined)
    if sports_hits >= 2:
        # Check if it has threat keywords (sports violence = keep)
        threat_check = any(t in combined for t in ["attack", "shooting", "killed", "bomb", "explosion", "riot", "stabbing"])
        if not threat_check:
            matching_terms = [term for term in SPORTS_TERMS if term in combined][:3]
            return True, "sports", f"Sports content ({', '.join(matching_terms)})"
    
    # Entertainment detection
    entertainment_hits = sum(1 for term in ENTERTAINMENT_TERMS if term in combined)
    if entertainment_hits >= 2:
        matching_terms = [term for term in ENTERTAINMENT_TERMS if term in combined][:3]
        return True, "entertainment", f"Entertainment content ({', '.join(matching_terms)})"
    
    # Routine politics detection
    politics_hits = sum(1 for term in POLITICAL_ROUTINE_TERMS if term in combined)
    if politics_hits >= 2:
        # Check if it's a political threat
        threat_check = any(t in combined for t in ["coup", "assassination", "killed", "attack", "riot", "bomb", "shooting"])
        if not threat_check:
            matching_terms = [term for term in POLITICAL_ROUTINE_TERMS if term in combined][:3]
            return True, "politics", f"Routine politics ({', '.join(matching_terms)})"
    
    # Cultural/religious routine events
    cultural_hits = sum(1 for term in CULTURAL_RELIGIOUS_TERMS if term in combined)
    if cultural_hits >= 2:
        # Check if it's a religious attack
        threat_check = any(t in combined for t in ["attack", "bomb", "shooting", "killed", "fire", "arson", "terrorism"])
        if not threat_check:
            matching_terms = [term for term in CULTURAL_RELIGIOUS_TERMS if term in combined][:3]
            return True, "cultural", f"Cultural/religious event ({', '.join(matching_terms)})"
    
    return False, "", ""

def scan_for_noise_alerts(cursor):
    """Scan database for low-quality alerts."""
    print("\n🔍 Scanning for low-quality alerts...")
    
    query = """
    SELECT id, uuid, title, summary, score, published, source
    FROM alerts
    WHERE title IS NOT NULL
    ORDER BY published DESC
    """
    
    cursor.execute(query)
    all_alerts = cursor.fetchall()
    
    print(f"📊 Scanning {len(all_alerts)} total alerts...")
    
    noise_alerts = []
    by_type = {"sports": 0, "entertainment": 0, "politics": 0, "cultural": 0}
    
    for alert in all_alerts:
        title = alert['title'] or ""
        summary = alert['summary'] or ""
        
        is_noise, noise_type, reason = detect_noise_content(title, summary)
        
        if is_noise:
            noise_alerts.append({
                'id': alert['id'],
                'uuid': alert['uuid'],
                'title': title[:80],
                'score': alert['score'],
                'noise_type': noise_type,
                'reason': reason,
                'published': alert['published'],
                'source': alert['source']
            })
            by_type[noise_type] = by_type.get(noise_type, 0) + 1
    
    return noise_alerts, by_type

def delete_noise_alerts(cursor, noise_alerts, dry_run=True):
    """Delete noise alerts from both alerts and raw_alerts tables."""
    if not noise_alerts:
        print("\n✨ No noise alerts found!")
        return 0
    
    print(f"\n🗑️  {'Would delete' if dry_run else 'Deleting'} {len(noise_alerts)} low-quality alerts...")
    
    deleted_count = 0
    
    for alert in noise_alerts:
        print(f"\n❌ Alert ID {alert['id']} - {alert['noise_type'].upper()}")
        print(f"   Title: {alert['title']}...")
        print(f"   Score: {alert['score']}")
        print(f"   Reason: {alert['reason']}")
        print(f"   Source: {alert['source']}")
        
        if not dry_run:
            # Delete from both tables
            cursor.execute("DELETE FROM alerts WHERE id = %s", (alert['id'],))
            cursor.execute("DELETE FROM raw_alerts WHERE uuid = %s", (alert['uuid'],))
            deleted_count += 1
            print(f"   🗑️  Deleted!")
    
    return deleted_count

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Clean up low-quality alerts')
    parser.add_argument('--execute', action='store_true', 
                       help='Actually delete alerts (default is dry-run)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Maximum number of alerts to delete (safety limit)')
    args = parser.parse_args()
    
    dry_run = not args.execute
    
    if dry_run:
        print("="*70)
        print("🔍 DRY RUN MODE - No changes will be made")
        print("   Run with --execute to actually delete alerts")
        print("="*70)
    else:
        print("="*70)
        print("⚠️  EXECUTE MODE - Alerts will be DELETED")
        print("="*70)
        response = input("Are you sure you want to delete low-quality alerts? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Aborted")
            sys.exit(0)
    
    # Connect to database
    print("\n📡 Connecting to database...")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Scan for noise alerts
        noise_alerts, by_type = scan_for_noise_alerts(cursor)
        
        print("\n" + "="*70)
        print("📊 SCAN RESULTS")
        print("="*70)
        print(f"Total low-quality alerts found: {len(noise_alerts)}")
        print(f"  - Sports: {by_type['sports']}")
        print(f"  - Entertainment: {by_type['entertainment']}")
        print(f"  - Routine politics: {by_type['politics']}")
        print(f"  - Cultural events: {by_type['cultural']}")
        
        if not noise_alerts:
            print("\n✨ Database is clean - no low-quality alerts found!")
            return
        
        # Apply limit if specified
        if args.limit and len(noise_alerts) > args.limit:
            print(f"\n⚠️  Limiting to {args.limit} alerts (safety limit)")
            noise_alerts = noise_alerts[:args.limit]
        
        # Show examples
        print("\n📋 Examples of low-quality alerts:")
        for alert in noise_alerts[:10]:
            print(f"  • [{alert['noise_type']}] {alert['title']}...")
        
        if len(noise_alerts) > 10:
            print(f"  ... and {len(noise_alerts) - 10} more")
        
        # Delete alerts
        deleted_count = delete_noise_alerts(cursor, noise_alerts, dry_run)
        
        if not dry_run:
            conn.commit()
            print("\n✅ Changes committed to database")
        else:
            print("\n🔍 Dry run complete - no changes made")
            print("   Run with --execute to actually delete alerts")
        
        # Summary
        print("\n" + "="*70)
        print("🎉 CLEANUP SUMMARY")
        print("="*70)
        
        if dry_run:
            print(f"Would delete: {len(noise_alerts)} low-quality alerts")
            print(f"  - Sports: {by_type['sports']}")
            print(f"  - Entertainment: {by_type['entertainment']}")
            print(f"  - Routine politics: {by_type['politics']}")
            print(f"  - Cultural events: {by_type['cultural']}")
        else:
            print(f"Deleted: {deleted_count} low-quality alerts")
            print(f"  - Sports: {by_type['sports']}")
            print(f"  - Entertainment: {by_type['entertainment']}")
            print(f"  - Routine politics: {by_type['politics']}")
            print(f"  - Cultural events: {by_type['cultural']}")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
        print("\n📡 Database connection closed")

if __name__ == "__main__":
    main()
