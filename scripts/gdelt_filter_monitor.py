#!/usr/bin/env python3
"""gdelt_filter_monitor.py
Periodic monitor for /admin/gdelt/filter-stats endpoint.

Features:
- Polls the filter stats endpoint at a configurable interval.
- Logs metrics (filtered counts, thresholds, enable flag).
- Appends CSV line for historical tracking (optional).

Environment:
  GDELT_MONITOR_BASE_URL  Base URL of service (default http://localhost:8000)
  GDELT_MONITOR_CSV       Path to CSV file (default gdelt_filter_metrics.csv)

Usage:
  python scripts/gdelt_filter_monitor.py --once
  python scripts/gdelt_filter_monitor.py --interval 300
"""
import os
import time
import json
import argparse
import datetime as dt
import requests

def fetch_stats(base_url: str):
    url = base_url.rstrip('/') + '/admin/gdelt/filter-stats'
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e), "url": url}

def write_csv(path: str, ts: dt.datetime, data: dict):
    header_fields = [
        "timestamp","filters_enabled","filtered_rows","ingest_rows","min_goldstein",
        "min_mentions","min_tone","max_age_hours","allowed_event_codes_count"
    ]
    if not os.path.exists(path):
        with open(path, 'w') as f:
            f.write(','.join(header_fields) + '\n')
    row = [
        ts.isoformat(),
        str(data.get('filters_enabled')),
        str(data.get('filtered_rows')),
        str(data.get('ingest_rows')),
        str(data.get('min_goldstein')),
        str(data.get('min_mentions')),
        str(data.get('min_tone')),
        str(data.get('max_age_hours')),
        str(data.get('allowed_event_codes_count')),
    ]
    with open(path, 'a') as f:
        f.write(','.join(row) + '\n')

def main():
    parser = argparse.ArgumentParser(description="Monitor GDELT filter stats endpoint")
    parser.add_argument('--interval', type=int, default=300, help='Polling interval seconds (default 300)')
    parser.add_argument('--once', action='store_true', help='Fetch only once then exit')
    parser.add_argument('--csv', type=str, default=os.getenv('GDELT_MONITOR_CSV','gdelt_filter_metrics.csv'), help='CSV output path')
    args = parser.parse_args()

    base_url = os.getenv('GDELT_MONITOR_BASE_URL','http://localhost:8000')

    def one_cycle():
        ts = dt.datetime.utcnow()
        data = fetch_stats(base_url)
        print(f"[{ts.isoformat()}] GDELT filter stats: {json.dumps(data, ensure_ascii=False)}")
        if 'error' not in data:
            write_csv(args.csv, ts, data)

    if args.once:
        one_cycle()
        return

    while True:
        one_cycle()
        time.sleep(args.interval)

if __name__ == '__main__':
    main()
