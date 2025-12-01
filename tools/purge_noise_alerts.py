#!/usr/bin/env python3
"""Purge clearly non-risk / entertainment RSS alerts (horoscope, astrology, etc.).

Usage:
  python tools/purge_noise_alerts.py            # Dry-run (default) shows counts & sample UUIDs
  python tools/purge_noise_alerts.py --delete   # Perform deletion
  python tools/purge_noise_alerts.py --limit 200 --delete  # Limit deletions

Environment:
  DATABASE_URL (if db_utils expects it) or existing db_utils connection settings.

Safety:
  - Only targets source='rss'.
  - Matches against title OR summary ILIKE any denylist token.
  - Default denylist aligns with rss_processor _RSS_DENYLIST_DEFAULT.
  - Uses LIMIT for staged removal.
"""
import os, sys, pathlib
from typing import List

DENYLIST = [
    "horoscope", "horoscopo", "horóscopo", "zodiac", "astrology", "astrological", "tarot",
    "celebrity", "entertainment", "lifestyle", "fashion", "beauty", "recipe", "cooking",
    "oscars", "hollywood", "film festival", "music awards", "tv show", "series finale",
]

# Allow runtime extension
extra = os.getenv("PURGE_EXTRA_NOISE", "").strip()
if extra:
    for part in extra.split(','):
        p = part.strip().lower()
        if p and p not in DENYLIST:
            DENYLIST.append(p)

# Build OR predicates safely
def _build_condition_and_params(tokens: List[str]):
    parts = []
    params: List[str] = []
    for t in tokens:
        # Use two predicates per token, parameterized
        parts.append("(title ILIKE %s OR summary ILIKE %s)")
        pat = f"%{t}%"
        params.extend([pat, pat])
    condition = "(" + " OR ".join(parts) + ")"
    return condition, tuple(params)

CONDITION, CONDITION_PARAMS = _build_condition_and_params(DENYLIST)

LIMIT_DEFAULT = 500

def main(argv: List[str]) -> int:
    delete = "--delete" in argv
    limit = LIMIT_DEFAULT
    for i, a in enumerate(argv):
        if a == "--limit" and i + 1 < len(argv):
            try:
                limit = int(argv[i+1])
            except ValueError:
                pass
    try:
        # Ensure parent directory (project root) is on path when executed from tools/
        root_dir = pathlib.Path(__file__).resolve().parent.parent
        if str(root_dir) not in sys.path:
            sys.path.append(str(root_dir))
        from utils.db_utils import fetch_one, fetch_all, execute
    except Exception as e:
        print(f"db_utils import failed: {e}", file=sys.stderr)
        return 2

    # Count matches
    # Do not restrict source: horoscope can appear on many domains. Language gate optional.
    count_row = fetch_one(f"SELECT count(*) FROM raw_alerts WHERE {CONDITION}", CONDITION_PARAMS)
    total_matches = count_row[0] if count_row else 0
    print(f"Noise candidate alerts (rss) matching denylist: {total_matches}")
    if total_matches == 0:
        return 0

    sample_rows = fetch_all(f"SELECT uuid, title FROM raw_alerts WHERE {CONDITION} ORDER BY published DESC LIMIT 20", CONDITION_PARAMS)
    print("Sample UUIDs:")
    for row in sample_rows:
        u = row.get('uuid') if isinstance(row, dict) else row[0]
        t = row.get('title') if isinstance(row, dict) else row[1]
        print(f" - {u} | {t[:90] if t else ''}")

    if not delete:
        print("Dry-run only. Pass --delete to remove. Use --limit N to cap batch size.")
        return 0

    # Perform deletion in limited batch
    del_count_row = fetch_one(f"SELECT count(*) FROM raw_alerts WHERE {CONDITION} LIMIT {limit}", CONDITION_PARAMS)
    # Some Postgres versions ignore LIMIT in count; fallback to selecting UUIDs then deleting
    uuids_rows = fetch_all(f"SELECT uuid FROM raw_alerts WHERE {CONDITION} ORDER BY published DESC LIMIT {limit}", CONDITION_PARAMS)
    uuids = [r.get('uuid') if isinstance(r, dict) else r[0] for r in uuids_rows]
    if not uuids:
        print("No rows selected for deletion.")
        return 0

    # Delete using UUID list for precision
    placeholders = ','.join(['%s'] * len(uuids))
    execute(f"DELETE FROM raw_alerts WHERE uuid IN ({placeholders})", tuple(uuids))
    print(f"Deleted {len(uuids)} noise alerts.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
