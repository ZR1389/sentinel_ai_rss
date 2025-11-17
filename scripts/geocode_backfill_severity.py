#!/usr/bin/env python3
import os
import sys
import argparse
from pathlib import Path
from typing import List, Dict

import psycopg2
import psycopg2.extras

# Ensure project root on path to import geocoding_service
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from geocoding_service import batch_geocode, _normalize_location


def fetch_alert_backlog(conn, limit: int) -> List[Dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id,
                   TRIM(BOTH ' ' FROM CONCAT_WS(', ', NULLIF(city,''), NULLIF(country,''))) AS location_text
            FROM alerts
            WHERE (latitude IS NULL OR longitude IS NULL)
              AND (COALESCE(city,'') <> '' OR COALESCE(country,'') <> '')
            ORDER BY (
                CASE 
                  WHEN (score::text) ~ '^[0-9]+(\\.[0-9]+)?$' THEN (score::text)::numeric 
                  ELSE 0 
                END
            ) DESC NULLS LAST,
            published DESC NULLS LAST
            LIMIT %s
            """,
            (limit,)
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows if r.get('location_text')]


def update_alert_coords(conn, updates: List[Dict]):
    if not updates:
        return 0
    with conn.cursor() as cur:
        for item in updates:
            cur.execute(
                """
                UPDATE alerts
                SET latitude = %s, longitude = %s
                WHERE id = %s
                """,
                (item['lat'], item['lon'], item['id'])
            )
    conn.commit()
    return len(updates)


def main():
    parser = argparse.ArgumentParser(description="Backfill geocoding for alerts with severity-first and dedup")
    parser.add_argument("--dsn", help="Postgres DSN (overrides DATABASE_URL)")
    parser.add_argument("--limit", type=int, default=1000, help="Max alerts to fetch per run")
    parser.add_argument("--max-api-calls", type=int, default=500, help="Max external API calls this run")
    args = parser.parse_args()

    if args.dsn:
        os.environ['DATABASE_URL'] = args.dsn
        dsn = args.dsn
    else:
        dsn = os.getenv('DATABASE_URL')
    if not dsn:
        print("ERROR: DATABASE_URL not set; pass --dsn or export it.")
        sys.exit(1)

    try:
        with psycopg2.connect(dsn=dsn) as conn:
            backlog = fetch_alert_backlog(conn, args.limit)
            if not backlog:
                print("No alerts need geocoding.")
                return

            # Build unique normalized locations
            uniq_locations = []
            seen = set()
            for r in backlog:
                norm = _normalize_location(r['location_text'])
                if norm and norm not in seen:
                    uniq_locations.append(r['location_text'])
                    seen.add(norm)

            # Geocode with cache-first; cap external calls
            geocoded_map = batch_geocode(uniq_locations, max_api_calls=args.max_api_calls)

            # Prepare updates
            updates = []
            for r in backlog:
                loc = r['location_text']
                res = geocoded_map.get(loc)
                if res and res.get('lat') is not None and res.get('lon') is not None:
                    updates.append({'id': r['id'], 'lat': res['lat'], 'lon': res['lon']})

            updated = update_alert_coords(conn, updates)
            print(f"Updated {updated} alerts with coordinates (from {len(backlog)} candidates).")

    except Exception as e:
        print(f"ERROR: Backfill failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
