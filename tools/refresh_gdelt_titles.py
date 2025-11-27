#!/usr/bin/env python3
"""
Refresh titles and summaries for recent GDELT alerts using updated enrichment logic.
- Scans `raw_alerts` where source='gdelt' over the last X days (default: 30)
- Rebuilds title/summary via functions from gdelt_enrichment_worker
- Updates rows in-place; preserves other fields
"""
import os
import sys
import logging
from datetime import datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger('refresh_gdelt_titles')

# DB URL
DATABASE_URL = os.getenv('DATABASE_PUBLIC_URL') or os.getenv('DATABASE_URL')
if not DATABASE_URL or DATABASE_URL.startswith('sqlite'):
    try:
        from config import CONFIG
        DATABASE_URL = CONFIG.database.url
    except Exception:
        pass
if not DATABASE_URL:
    raise RuntimeError('DATABASE_URL or DATABASE_PUBLIC_URL must be set')

# Ensure repo root on sys.path for module imports
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Import helpers from enrichment worker
from gdelt_enrichment_worker import build_gdelt_summary, get_event_description, clean_actor, _resolve_country_name

DEFAULT_DAYS = int(os.getenv('REFRESH_GDELT_DAYS', '30'))
DEFAULT_BATCH_LIMIT = int(os.getenv('REFRESH_GDELT_LIMIT', '5000'))


def run(days: int = DEFAULT_DAYS, all_time: bool = False, batch_limit: int = DEFAULT_BATCH_LIMIT):
    cutoff = None if all_time else (datetime.now(timezone.utc) - timedelta(days=days))
    if all_time:
        logger.info('Refreshing GDELT titles/summaries for all time')
    else:
        logger.info('Refreshing GDELT titles/summaries since %s (last %d days)', cutoff.isoformat(), days)
    conn = psycopg2.connect(DATABASE_URL)
    updated = 0
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if all_time:
                    cur.execute(
                        """
                        SELECT id, uuid, title, summary, country, tags
                        FROM raw_alerts
                        WHERE source = 'gdelt'
                        ORDER BY published DESC
                        LIMIT %s
                        """,
                        (batch_limit,)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, uuid, title, summary, country, tags
                        FROM raw_alerts
                        WHERE source = 'gdelt'
                          AND published >= %s
                        ORDER BY published DESC
                        LIMIT %s
                        """,
                        (cutoff, batch_limit)
                    )
                rows = cur.fetchall()
                logger.info('Found %d GDELT alerts to refresh (limit=%d)', len(rows), batch_limit)
                for row in rows:
                    # Extract original event fields from tags JSON
                    try:
                        import json
                        raw_tags = row['tags']
                        # tags can be stored as JSON string or already as list
                        if isinstance(raw_tags, (list, tuple)):
                            tags = list(raw_tags)
                        elif isinstance(raw_tags, (str, bytes, bytearray)) and raw_tags:
                            try:
                                tags = json.loads(raw_tags)
                            except Exception:
                                # Some rows may store a Python list string; try eval safely
                                tags = []
                        else:
                            tags = []
                        meta = tags[0] if isinstance(tags, list) and tags else {}
                        event_code = meta.get('event_code')
                        actor1 = meta.get('actor1')
                        actor2 = meta.get('actor2')
                        country = row.get('country')
                        event_description = get_event_description(event_code)
                        a1 = clean_actor(actor1)
                        a2 = clean_actor(actor2)
                        a1c = _resolve_country_name(a1)
                        a2c = _resolve_country_name(a2)
                        # Title generation mirroring updated logic
                        if a1 and a2 and a2c:
                            subject = a1 if not a1c else None
                            title = f"{(subject + ' ') if subject else ''}{event_description} involving {a2c}"
                        elif a1 and not a1c:
                            title = f"{a1} {event_description}"
                        else:
                            pretty_event = event_description.capitalize()
                            title = f"{pretty_event} in {country or 'Unknown'}"
                        # Summary via worker util
                        summary = build_gdelt_summary({
                            'actor1': actor1,
                            'actor2': actor2,
                            'event_code': event_code,
                            'quad_class': meta.get('quad_class'),
                            'action_country': country or 'Unknown',
                            'goldstein': meta.get('goldstein'),
                            'num_articles': meta.get('num_articles'),
                            'num_sources': meta.get('num_sources')
                        })
                        # Update DB if changed
                        if title != row['title'] or summary != row['summary']:
                            cur.execute(
                                """
                                UPDATE raw_alerts
                                SET title = %s, summary = %s
                                WHERE id = %s
                                """,
                                (title, summary, row['id'])
                            )
                            updated += 1
                    except Exception as e:
                        logger.warning('Skipping alert %s: %s', row.get('uuid'), e)
        logger.info('Updated %d GDELT alerts', updated)
    finally:
        conn.close()
    return updated


if __name__ == '__main__':
    days = DEFAULT_DAYS
    all_time = False
    batch_limit = DEFAULT_BATCH_LIMIT
    args = sys.argv[1:]
    for a in args:
        al = a.lower()
        if al in ('all', 'all-time', '--all'):
            all_time = True
        elif al.startswith('--limit='):
            try:
                batch_limit = int(al.split('=',1)[1])
            except Exception:
                pass
        else:
            try:
                days = int(al)
            except Exception:
                pass
    count = run(days, all_time=all_time, batch_limit=batch_limit)
    if all_time:
        print(f"Refreshed {count} GDELT alerts (all time, up to {batch_limit})")
    else:
        print(f"Refreshed {count} GDELT alerts in last {days} days (limit={batch_limit})")
