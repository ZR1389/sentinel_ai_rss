# GDELT Pipeline: Coordinate Validation & Alert Generation - Fixed

## Issue Summary
GDELT pipeline was producing **zero final alerts** despite ingesting thousands of events, due to:
1. Invalid coordinate data (timestamps/large integers in lat/long fields)
2. Threat Engine validation rejection (strict -90/90 lat, -180/180 long bounds)
3. Zero-incident filter excluding intelligence sources

## Fixes Implemented

### 1. Ingest Coordinate Sanitation (`gdelt_ingest.py`)
**Changes:**
- Added coordinate bounds check before batch insert
- Null invalid latitude (outside ±90) or longitude (outside ±180 or ==0)
- Added `geo_invalid_rows` metric counter
- Updated ingest log to show sanitized count

**Code Added:**
```python
# Coordinate sanitation: replace out-of-range values with None
lat = mapped['action_lat']
lon = mapped['action_long']
if lat is not None and (lat < -90 or lat > 90):
    mapped['action_lat'] = None
    _ingest_metrics["geo_invalid_rows"] += 1
if lon is not None and (lon == 0.0 or lon < -180 or lon > 180):
    mapped['action_long'] = None
    _ingest_metrics["geo_invalid_rows"] += 1
```

### 2. Raw Alert Cleanup (`gdelt_coordinate_cleanup.py`)
**Purpose:** Fix existing malformed rows in `raw_alerts` table.

**Usage:**
```bash
# Dry run (check counts only)
python gdelt_coordinate_cleanup.py --dry-run

# Execute cleanup
DATABASE_PUBLIC_URL='...' python gdelt_coordinate_cleanup.py
```

**Actions:**
- Sets latitude/longitude to NULL where out of bounds or lon==0
- Appends `geo_correction` tag to affected rows
- Reports before/after invalid counts

**Results:** Cleaned 58 invalid raw_alerts on first run.

### 3. Threat Engine Intelligence Exemption (`threat_engine.py`)
**Problem:** Zero-incident filter was blocking GDELT/ACLED alerts.

**Fix:**
```python
# Skip zero-incident filter for intelligence sources
zero_incidents = (alert.get("incident_count_30d", 0) == 0 and alert.get("recent_count_7d", 0) == 0)
is_intel = (str(alert.get("source",""))).lower() in ("gdelt", "acled") or (str(alert.get("source_kind",""))).lower() == "intelligence"
if zero_incidents and not is_intel:
    logger.info(f"Skipping alert with zero incidents...")
    return None  # Don't enrich zero-incident alerts from non-intel sources
```

## Verification

### Before Fixes:
- GDELT alerts last 24h: 0
- Raw alerts: 1,000 created but invalid coordinates blocked final alert creation

### After Fixes:
- GDELT alerts last 24h: **13**
- GDELT alerts last 1h: **13**
- Total alerts in system: 1,524

### Commands Used:
```bash
# 1. Run cleanup
DATABASE_PUBLIC_URL='postgresql://...' python gdelt_coordinate_cleanup.py

# 2. Run threat engine via wrapper
cd /home/zika/sentinel_ai_rss && \
DATABASE_PUBLIC_URL='postgresql://...' \
DATABASE_URL='postgresql://...' \
./run_cron.sh engine

# 3. Verify alert creation
python -c "
from db_utils import _get_db_connection
with _get_db_connection() as conn:
    cur = conn.cursor()
    cur.execute(\"SELECT COUNT(*) FROM alerts WHERE source='gdelt' AND created_at > NOW() - INTERVAL '1 hour'\")
    print(f'GDELT alerts last 1h: {cur.fetchone()[0]}')
"
```

## Ongoing Monitoring

### Ingest Metrics
Monitor `geo_invalid_rows` in ingest logs:
```
[gdelt] Ingested 1500 new events (skipped: 50, geo_sanitized: 12, duration: 5.2s)
```

### Pipeline Health Check
```sql
-- Raw alerts with coordinates
SELECT COUNT(*) FROM raw_alerts WHERE source='gdelt' AND latitude IS NOT NULL;

-- Final alerts generated
SELECT COUNT(*) FROM alerts WHERE source='gdelt' AND created_at > NOW() - INTERVAL '1 day';
```

## Next Steps

1. **LLM Provider Setup:** DeepSeek API exhausted (402 errors); configure alternate provider:
   ```bash
   # Set in Railway or .env
   LLM_PRIMARY_ENRICHMENT=grok
   LLM_SECONDARY_VERIFICATION=openai
   ```

2. **Continuous Enrichment:** Start enrichment worker:
   ```bash
   DATABASE_PUBLIC_URL='...' python gdelt_enrichment_worker.py
   ```

3. **Automated Cron:** Ensure Railway cron has correct DATABASE_URL:
   ```bash
   # In Railway dashboard cron job
   DATABASE_URL=$DATABASE_PUBLIC_URL ./run_cron.sh engine
   ```

## Files Modified
- `gdelt_ingest.py` - Added coordinate sanitation
- `gdelt_coordinate_cleanup.py` - Created cleanup script
- `threat_engine.py` - Exempted intelligence from zero-incident filter

## Deployment Notes
- Ingest sanitation is **forward-compatible** (no schema changes)
- Cleanup script is **idempotent** (safe to rerun)
- Engine change is **backward-compatible** (still filters RSS zero-incidents)
- Database URL precedence: `DATABASE_PUBLIC_URL` > `DATABASE_URL` (via env_utils bootstrap)
