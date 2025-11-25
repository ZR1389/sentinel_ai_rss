"""gdelt_ingest.py

Minimal GDELT 2.0 export ingestor (Phase 1 + refinements)

Focus: Fetch the lastupdate.txt every interval (default 15m), download the latest
export CSV ZIP (ignore mentions + gkg for now), extract events and persist core
fields + full raw row JSON for future enrichment.

Environment Variables (optional):
  GDELT_ENABLED=true              # enable background polling
  GDELT_POLL_INTERVAL_MIN=15      # minutes between polls
  GDELT_RETRY_ATTEMPTS=3          # max retries for 404/network errors
  GDELT_RETRY_BACKOFF=5           # seconds between retries
  GDELT_ENABLE_FILTERS=true       # enable aggressive filtering (see gdelt_filters.py)

Schema (created automatically if missing):
  gdelt_events(
      global_event_id BIGINT PRIMARY KEY,
      sql_date INTEGER,
      actor1 TEXT,
      actor2 TEXT,
      event_code TEXT,
      event_root_code TEXT,
      quad_class INTEGER,
      goldstein FLOAT,
      num_mentions INTEGER,
      num_sources INTEGER,
      num_articles INTEGER,
      avg_tone FLOAT,
      action_country TEXT,
      action_lat FLOAT,
      action_long FLOAT,
      raw JSONB,
      created_at TIMESTAMPTZ DEFAULT now(),
      source_url TEXT,
      processed BOOLEAN DEFAULT false
  )

  gdelt_state(
      key TEXT PRIMARY KEY,
      value TEXT
  )  -- used for last_processed_export filename

NOTE: We only process a new export file if its filename differs from the last processed.
"""

from __future__ import annotations
import os
import threading
import time
import logging
import requests
import zipfile
import io
import csv
from typing import Dict, List, Optional

logger = logging.getLogger("gdelt_ingest")

GDELT_LASTUPDATE = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"

_poll_thread_started = False

# Configurable retry params from env
GDELT_RETRY_ATTEMPTS = int(os.getenv("GDELT_RETRY_ATTEMPTS", "3"))
GDELT_RETRY_BACKOFF = int(os.getenv("GDELT_RETRY_BACKOFF", "5"))

# Enable aggressive filtering (gdelt_filters.py)
GDELT_ENABLE_FILTERS = os.getenv("GDELT_ENABLE_FILTERS", "false").lower() in ("true", "1", "yes")

# Metrics tracking
_ingest_metrics = {
    "total_rows_processed": 0,
    "skipped_rows": 0,
    "filtered_rows": 0,  # New: track filter rejections
    "retries_performed": 0,
    "successful_ingests": 0,
    "failed_ingests": 0
}

def safe_int(val, default=0):
    """Convert to int, returning default on failure."""
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default

def safe_float(val, default=0.0):
    """Convert to float, returning default on failure."""
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default

def fetch_with_retry(url: str, max_retries: int = None, backoff: int = None):
    """Fetch URL with retry on transient 404 (GDELT delay) and network errors.
    Returns Response or None.
    """
    if max_retries is None:
        max_retries = GDELT_RETRY_ATTEMPTS
    if backoff is None:
        backoff = GDELT_RETRY_BACKOFF
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 404 and attempt < max_retries - 1:
                _ingest_metrics["retries_performed"] += 1
                logger.warning("[gdelt] 404 for %s (attempt %d/%d) – retrying in %ds", url, attempt+1, max_retries, backoff)
                time.sleep(backoff)
                continue
            # Other status codes: raise
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                logger.error("[gdelt] Request failed final attempt (%s): %s", url, e)
                return None
            _ingest_metrics["retries_performed"] += 1
            logger.warning("[gdelt] Request error (%s) attempt %d/%d: %s – retrying in %ds", url, attempt+1, max_retries, e, backoff)
            time.sleep(backoff)
    return None

def _get_db_helpers():
    try:
        from db_utils import _get_db_connection
        return _get_db_connection
    except Exception as e:
        logger.error("[gdelt] DB helpers unavailable: %s", e)
        return None

def ensure_tables():
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gdelt_events (
                  global_event_id BIGINT PRIMARY KEY,
                  sql_date INTEGER,
                  actor1 TEXT,
                  actor2 TEXT,
                  event_code TEXT,
                  event_root_code TEXT,
                  quad_class INTEGER,
                  goldstein FLOAT,
                  num_mentions INTEGER,
                  num_sources INTEGER,
                  num_articles INTEGER,
                  avg_tone FLOAT,
                  action_country TEXT,
                  action_lat FLOAT,
                  action_long FLOAT,
                  raw JSONB,
                  created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gdelt_state (
                  key TEXT PRIMARY KEY,
                  value TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gdelt_metrics (
                  id SERIAL PRIMARY KEY,
                  timestamp TIMESTAMPTZ DEFAULT now(),
                  ingestion_duration_sec DECIMAL(10, 3),
                  events_downloaded INTEGER DEFAULT 0,
                  events_inserted INTEGER DEFAULT 0,
                  events_skipped INTEGER DEFAULT 0,
                  retries_performed INTEGER DEFAULT 0,
                  filename TEXT,
                  last_error TEXT
                )
                """
            )
        logger.info("[gdelt] Tables ensured")
    except Exception as e:
        logger.error("[gdelt] Failed ensuring tables: %s", e)

def get_latest_gdelt_urls() -> Dict[str, str]:
    urls: Dict[str, str] = {}
    try:
        resp = fetch_with_retry(GDELT_LASTUPDATE)
        if not resp:
            logger.error("[gdelt] Failed to fetch lastupdate.txt")
            return urls
        lines = resp.text.strip().split('\n')
        for line in lines:
            parts = line.split()
            # lastupdate lines format: unix_timestamp yyyymmddhhmmss file_url
            if len(parts) >= 3:
                url = parts[2]
                if 'export.CSV.zip' in url:
                    urls['export'] = url
                elif 'mentions.CSV.zip' in url:
                    urls['mentions'] = url
                elif 'gkg.csv.zip' in url:
                    urls['gkg'] = url
    except Exception as e:
        logger.error("[gdelt] Error fetching lastupdate: %s", e)
    return urls

def _get_last_processed_filename() -> Optional[str]:
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return None
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM gdelt_state WHERE key='last_export_file'")
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.warning("[gdelt] Could not read state: %s", e)
        return None

def _set_last_processed_filename(name: str):
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO gdelt_state(key,value) VALUES('last_export_file', %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                (name,)
            )
    except Exception as e:
        logger.warning("[gdelt] Could not persist state: %s", e)

def _log_metric(duration_sec: float, events_downloaded: int, events_inserted: int, 
                events_skipped: int, retries: int, filename: str, error: str = None):
    """Persist ingestion metrics to gdelt_metrics table."""
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO gdelt_metrics(
                  ingestion_duration_sec, events_downloaded, events_inserted, 
                  events_skipped, retries_performed, filename, last_error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (round(duration_sec, 3), events_downloaded, events_inserted, 
                 events_skipped, retries, filename, error)
            )
    except Exception as e:
        logger.warning("[gdelt] Failed to log metric: %s", e)

def _parse_and_store_export(zip_bytes: bytes, filename: str) -> int:
    """Extract ZIP containing one export CSV and store rows. Returns inserted count."""
    import time
    start_time = time.time()
    inserted = 0
    events_downloaded = 0
    skipped_this_run = 0
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return 0
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_name = None
            for n in zf.namelist():
                if n.endswith(".export.CSV"):
                    csv_name = n
                    break
            if not csv_name:
                logger.warning("[gdelt] No export CSV found inside %s", filename)
                return 0
            with zf.open(csv_name) as f:
                # GDELT export is tab-delimited
                text = io.TextIOWrapper(f, encoding='utf-8', errors='replace')
                reader = csv.reader(text, delimiter='\t')
                rows_batch: List[Dict] = []
                batch_size = 1000
                with get_conn_cm() as conn:
                    cur = conn.cursor()
                    for row in reader:
                        events_downloaded += 1
                        _ingest_metrics["total_rows_processed"] += 1
                        if not row or len(row) < 10:
                            skipped_this_run += 1
                            _ingest_metrics["skipped_rows"] += 1
                            continue
                        try:
                            global_event_id = safe_int(row[0])
                            if global_event_id == 0:
                                skipped_this_run += 1
                                _ingest_metrics["skipped_rows"] += 1
                                continue
                        except Exception:
                            skipped_this_run += 1
                            _ingest_metrics["skipped_rows"] += 1
                            continue
                        # Defensive length access helpers
                        def gv(i, default=None):
                            return row[i] if i < len(row) else default
                        # Minimal mapping indices per official schema
                        # 0 GlobalEventID, 1 SQLDate, 6 Actor1Name, 16 Actor2Name,
                        # 26 EventCode, 27 EventRootCode, 29 QuadClass, 30 GoldsteinScale,
                        # 31 NumMentions, 32 NumSources, 33 NumArticles, 34 AvgTone,
                        # 55 ActionGeo_CountryCode, 58 ActionGeo_Lat, 59 ActionGeo_Long
                        mapped = {
                            'global_event_id': global_event_id,
                            'sql_date': safe_int(gv(1)),
                            'actor1': gv(6),
                            'actor2': gv(16),
                            'event_code': gv(26),
                            'event_root_code': gv(27),
                            'quad_class': safe_int(gv(29)),
                            'goldstein': safe_float(gv(30)),
                            'num_mentions': safe_int(gv(31)),
                            'num_sources': safe_int(gv(32)),
                            'num_articles': safe_int(gv(33)),
                            'avg_tone': safe_float(gv(34)),
                            'action_country': gv(55),
                            'action_lat': safe_float(gv(58)),  # Column 58 is ActionGeo_Lat
                            'action_long': safe_float(gv(59)),  # Column 59 is ActionGeo_Long
                            'raw': row
                        }
                        
                        # Apply aggressive filtering if enabled
                        if GDELT_ENABLE_FILTERS:
                            try:
                                from gdelt_filters import should_ingest_gdelt_event
                                if not should_ingest_gdelt_event(mapped, stage="ingest"):
                                    skipped_this_run += 1
                                    _ingest_metrics["filtered_rows"] += 1
                                    continue
                            except ImportError:
                                logger.warning("[gdelt] gdelt_filters.py not found; filter disabled")
                        
                        rows_batch.append(mapped)
                        if len(rows_batch) >= batch_size:
                            inserted += _flush_batch(cur, rows_batch)
                            rows_batch.clear()
                    if rows_batch:
                        inserted += _flush_batch(cur, rows_batch)
        _set_last_processed_filename(filename)
        _ingest_metrics["successful_ingests"] += 1
        duration = time.time() - start_time
        _log_metric(duration, events_downloaded, inserted, skipped_this_run, 
                   _ingest_metrics["retries_performed"], filename)
        logger.info("[gdelt] Ingested %d new events from %s (skipped: %d rows, duration: %.2fs)", 
                   inserted, filename, skipped_this_run, duration)
    except Exception as e:
        _ingest_metrics["failed_ingests"] += 1
        duration = time.time() - start_time
        _log_metric(duration, events_downloaded, inserted, skipped_this_run, 
                   _ingest_metrics["retries_performed"], filename, str(e))
        logger.error("[gdelt] Failed parsing export %s: %s", filename, e)
    return inserted

def _flush_batch(cur, batch: List[Dict]) -> int:
    if not batch:
        return 0
    # Build INSERT ... ON CONFLICT DO NOTHING
    import json
    values = [(
        r['global_event_id'], r['sql_date'], r['actor1'], r['actor2'], r['event_code'],
        r['event_root_code'], r['quad_class'], r['goldstein'], r['num_mentions'], r['num_sources'],
        r['num_articles'], r['avg_tone'], r['action_country'], r['action_lat'], r['action_long'],
        json.dumps(r['raw'])
    ) for r in batch]
    try:
        psycopg2_extras = None
        try:
            import psycopg2.extras as psycopg2_extras
        except Exception:
            pass
        if psycopg2_extras:
            psycopg2_extras.execute_values(
                cur,
                """
                INSERT INTO gdelt_events(
                  global_event_id, sql_date, actor1, actor2, event_code, event_root_code,
                  quad_class, goldstein, num_mentions, num_sources, num_articles, avg_tone,
                  action_country, action_lat, action_long, raw
                ) VALUES %s ON CONFLICT (global_event_id) DO NOTHING
                """,
                values,
                page_size=1000
            )
            return len(batch)
        else:
            inserted = 0
            for v in values:
                cur.execute(
                    """
                    INSERT INTO gdelt_events(
                      global_event_id, sql_date, actor1, actor2, event_code, event_root_code,
                      quad_class, goldstein, num_mentions, num_sources, num_articles, avg_tone,
                      action_country, action_lat, action_long, raw
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (global_event_id) DO NOTHING
                    """,
                    v
                )
                inserted += cur.rowcount or 0
            return inserted
    except Exception as e:
        logger.error("[gdelt] Batch insert failed: %s", e)
        return 0

def process_latest_export() -> int:
    """Fetch lastupdate, get export URL, download + ingest if new. Returns inserted count."""
    urls = get_latest_gdelt_urls()
    export_url = urls.get('export')
    if not export_url:
        logger.warning("[gdelt] No export URL found in lastupdate")
        return 0
    filename = export_url.rsplit('/', 1)[-1]
    last_file = _get_last_processed_filename()
    if last_file == filename:
        logger.info("[gdelt] Export %s already processed", filename)
        return 0
    resp = fetch_with_retry(export_url)
    if not resp:
        logger.error("[gdelt] Giving up download for %s", export_url)
        return 0
    return _parse_and_store_export(resp.content, filename)

def start_gdelt_polling():
    global _poll_thread_started
    if _poll_thread_started:
        return
    if os.getenv("GDELT_ENABLED", "false").lower() != "true":
        return
    interval_min = int(os.getenv("GDELT_POLL_INTERVAL_MIN", "15") or 15)
    ensure_tables()
    def _run():
        while True:
            try:
                process_latest_export()
            except Exception as e:
                logger.error("[gdelt] Poll iteration failed: %s", e)
            time.sleep(interval_min * 60)
    t = threading.Thread(target=_run, name="gdelt_poll", daemon=True)
    t.start()
    _poll_thread_started = True
    logger.info("[gdelt] Polling thread started (interval=%d min)", interval_min)

def get_ingest_metrics() -> Dict:
    """Return current ingest metrics for monitoring."""
    return dict(_ingest_metrics)

def manual_trigger() -> Dict[str, int]:
    """Manual ingestion trigger used by admin endpoint."""
    ensure_tables()
    inserted = process_latest_export()
    return {"inserted": inserted, "metrics": get_ingest_metrics()}
