#!/usr/bin/env python3
"""refresh_aggregates.py
Build or rebuild geographic / categorical aggregates for map display.

If the table `map_aggregates` does not exist it will be created.

Aggregations implemented:
  1. country-level counts
  2. city-level counts (only where city present AND coordinates present)
  3. category-level per country (optional flag)

By default all sources present in `alerts` are aggregated (excluding removed GDELT rows).
You can restrict with --sources and force deletion of prior rows with --truncate or selective delete with --delete-gdelt.

Schema (created if missing):
  map_aggregates(
      id SERIAL PRIMARY KEY,
      agg_type TEXT,               -- 'country' | 'city' | 'country_category'
      source TEXT,                 -- originating source domain or tag
      country TEXT,
      city TEXT,
      category TEXT,
      alert_count INTEGER,
      alerts_24h INTEGER,
      alerts_7d INTEGER,
      avg_score NUMERIC,
      min_published TIMESTAMP,
      max_published TIMESTAMP,
      latitude NUMERIC,            -- centroid (city-level)
      longitude NUMERIC,
      generated_at TIMESTAMP DEFAULT NOW()
  )

Indexes created for common query patterns.

Usage examples:
  python scripts/refresh_aggregates.py --truncate
  python scripts/refresh_aggregates.py --delete-gdelt
  python scripts/refresh_aggregates.py --sources rbc.ru g1.globo.com --no-city
  python scripts/refresh_aggregates.py --country-category
"""
import os
import sys
import argparse
from datetime import datetime, timedelta
from typing import List
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

def load_env():
    if os.path.exists('.env.production'):
        load_dotenv('.env.production', override=True)
    else:
        load_dotenv('.env', override=False)

def get_conn():
    url = os.getenv('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL not set')
    return psycopg2.connect(url)

def ensure_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS map_aggregates (
            id SERIAL PRIMARY KEY,
            agg_type TEXT NOT NULL,
            source TEXT NOT NULL,
            country TEXT,
            city TEXT,
            category TEXT,
            alert_count INTEGER NOT NULL,
            alerts_24h INTEGER,
            alerts_7d INTEGER,
            avg_score NUMERIC,
            min_published TIMESTAMP,
            max_published TIMESTAMP,
            latitude NUMERIC,
            longitude NUMERIC,
            generated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mapagg_type ON map_aggregates(agg_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mapagg_country ON map_aggregates(country)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mapagg_source ON map_aggregates(source)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mapagg_city ON map_aggregates(city)")

def fetch_sources(cur, restrict: List[str]):
    if restrict:
        return restrict
    cur.execute("SELECT DISTINCT source FROM alerts WHERE source IS NOT NULL AND source <> ''")
    return [r[0] for r in cur.fetchall()]

def delete_gdelt(cur):
    cur.execute("DELETE FROM map_aggregates WHERE source='gdelt'")

def truncate(cur):
    cur.execute("TRUNCATE map_aggregates")

def build_country(cur, sources: List[str]):
    sql = """
    SELECT source, country,
           COUNT(*) AS alert_count,
           SUM(CASE WHEN published >= NOW() - INTERVAL '24 hours' THEN 1 ELSE 0 END) AS alerts_24h,
           SUM(CASE WHEN published >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) AS alerts_7d,
           AVG(score) AS avg_score,
           MIN(published) AS min_published,
           MAX(published) AS max_published
    FROM alerts
    WHERE country IS NOT NULL AND country <> '' AND source = ANY(%s)
    GROUP BY source, country
    """
    cur.execute(sql, (sources,))
    rows = cur.fetchall()
    out = []
    for r in rows:
        source, country, count_all, c24, c7, avg_score, mn, mx = r
        out.append((
            'country', source, country, None, None,
            count_all, c24, c7, avg_score, mn, mx, None, None
        ))
    return out

def build_city(cur, sources: List[str]):
    sql = """
    SELECT source, country, city,
           AVG(latitude) AS lat_centroid,
           AVG(longitude) AS lon_centroid,
           COUNT(*) AS alert_count,
           SUM(CASE WHEN published >= NOW() - INTERVAL '24 hours' THEN 1 ELSE 0 END) AS alerts_24h,
           SUM(CASE WHEN published >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) AS alerts_7d,
           AVG(score) AS avg_score,
           MIN(published) AS min_published,
           MAX(published) AS max_published
    FROM alerts
    WHERE city IS NOT NULL AND city <> ''
      AND latitude IS NOT NULL AND longitude IS NOT NULL
      AND source = ANY(%s)
    GROUP BY source, country, city
    """
    cur.execute(sql, (sources,))
    rows = cur.fetchall()
    out = []
    for r in rows:
        source, country, city, lat, lon, count_all, c24, c7, avg_score, mn, mx = r
        out.append((
            'city', source, country, city, None,
            count_all, c24, c7, avg_score, mn, mx, lat, lon
        ))
    return out

def build_country_category(cur, sources: List[str]):
    sql = """
    SELECT source, country, category,
           COUNT(*) AS alert_count,
           SUM(CASE WHEN published >= NOW() - INTERVAL '24 hours' THEN 1 ELSE 0 END) AS alerts_24h,
           SUM(CASE WHEN published >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) AS alerts_7d,
           AVG(score) AS avg_score,
           MIN(published) AS min_published,
           MAX(published) AS max_published
    FROM alerts
    WHERE country IS NOT NULL AND country <> '' AND category IS NOT NULL AND category <> ''
      AND source = ANY(%s)
    GROUP BY source, country, category
    """
    cur.execute(sql, (sources,))
    rows = cur.fetchall()
    out = []
    for r in rows:
        source, country, category, count_all, c24, c7, avg_score, mn, mx = r
        out.append((
            'country_category', source, country, None, category,
            count_all, c24, c7, avg_score, mn, mx, None, None
        ))
    return out

def insert_rows(cur, rows):
    if not rows:
        return 0
    cols = [
        'agg_type','source','country','city','category','alert_count','alerts_24h','alerts_7d',
        'avg_score','min_published','max_published','latitude','longitude'
    ]
    execute_values(cur,
        f"INSERT INTO map_aggregates ({', '.join(cols)}) VALUES %s",
        rows
    )
    return len(rows)

def main():
    parser = argparse.ArgumentParser(description='Refresh map aggregates from alerts')
    parser.add_argument('--sources', nargs='*', help='Limit to specific sources')
    parser.add_argument('--truncate', action='store_true', help='Truncate entire map_aggregates table before rebuild')
    parser.add_argument('--delete-gdelt', action='store_true', help='Delete only gdelt rows before rebuild')
    parser.add_argument('--no-city', action='store_true', help='Skip city-level aggregation')
    parser.add_argument('--country-category', action='store_true', help='Include country/category rollups')
    parser.add_argument('--dry-run', action='store_true', help='Show counts without writing')
    args = parser.parse_args()

    load_env()
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            ensure_table(cur)
            sources = fetch_sources(cur, args.sources or [])
            # Remove gdelt if present but table cleaned already
            if 'gdelt' in sources:
                sources = [s for s in sources if s.lower() != 'gdelt']

            if args.truncate:
                truncate(cur)
            elif args.delete_gdelt:
                delete_gdelt(cur)

            country_rows = build_country(cur, sources)
            city_rows = [] if args.no_city else build_city(cur, sources)
            cc_rows = build_country_category(cur, sources) if args.country_category else []

            total_rows = len(country_rows) + len(city_rows) + len(cc_rows)
            print(f"Prepared aggregates: country={len(country_rows)} city={len(city_rows)} country_category={len(cc_rows)} total={total_rows}")

            if args.dry_run:
                print("Dry-run: no writes performed.")
                return

            written = insert_rows(cur, country_rows)
            written += insert_rows(cur, city_rows)
            written += insert_rows(cur, cc_rows)
            print(f"Inserted {written} aggregate rows.")

if __name__ == '__main__':
    main()
