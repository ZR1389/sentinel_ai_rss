#!/usr/bin/env python3
import os
import sys
import argparse
from pathlib import Path

# Ensure project root is on sys.path for db_utils import
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import psycopg2
import psycopg2.extras

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS country_centroids (
    country_code TEXT PRIMARY KEY,
    country_name TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL
);
"""

SQL_FILE = ROOT / "sql" / "country_centroids_bulk_insert.sql"


def main():
    parser = argparse.ArgumentParser(description="Bulk load country centroids")
    parser.add_argument("--dsn", help="Postgres DSN (overrides DATABASE_URL)")
    args = parser.parse_args()

    dsn = args.dsn or os.getenv("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL is not set in environment.")
        sys.exit(1)

    # Connect directly with psycopg2 to avoid CONFIG overrides
    try:
        with psycopg2.connect(dsn=dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLE_SQL)

            if not SQL_FILE.exists():
                print(f"ERROR: SQL file not found: {SQL_FILE}")
                sys.exit(1)

            sql_text = SQL_FILE.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql_text)

            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM country_centroids;")
                total = cur.fetchone()[0]
                print(f"country_centroids rows: {total}")
    except Exception as e:
        print(f"ERROR: Failed to load centroids: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
