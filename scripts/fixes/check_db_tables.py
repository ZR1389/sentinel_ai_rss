#!/usr/bin/env python3
"""Check database tables and row counts."""
import psycopg2
import os

db_url = os.getenv("DATABASE_URL")
conn = psycopg2.connect(db_url)
cur = conn.cursor()

print("\n=== ALL TABLES IN DATABASE ===")
cur.execute("""
    SELECT schemaname, tablename 
    FROM pg_tables 
    WHERE schemaname = 'public'
    ORDER BY tablename;
""")
tables = cur.fetchall()
for schema, table in tables:
    cur.execute(f"SELECT COUNT(*) FROM {table};")
    count = cur.fetchone()[0]
    print(f"  {table:40s} {count:>10,} rows")

print("\n=== CHECK IF 'alerts' TABLE EXISTS ===")
cur.execute("""
    SELECT EXISTS (
        SELECT FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name = 'alerts'
    );
""")
exists = cur.fetchone()[0]
print(f"  alerts table exists: {exists}")

if exists:
    print("\n=== ALERTS TABLE SCHEMA ===")
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'alerts'
        ORDER BY ordinal_position;
    """)
    for col_name, data_type, nullable in cur.fetchall():
        print(f"  {col_name:30s} {data_type:20s} NULL={nullable}")

cur.close()
conn.close()
