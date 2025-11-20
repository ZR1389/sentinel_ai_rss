# GDELT Aggressive Filtering

## Overview

Brutal GDELT event filtering to eliminate noise and focus on high-signal conflict/protest events.

## How It Works

The filter applies **8 strict criteria** at both ingestion and enrichment stages:

1. **Coordinates**: Valid lat/lon required (optionally reject 0,0 centroids)
2. **Goldstein Scale**: ≤ -5.0 (highly negative events only)
3. **Media Mentions**: ≥ 3 sources (multi-source verification)
4. **Average Tone**: ≤ -5.0 (significantly negative sentiment)
5. **Event Code Whitelist**: Only violence/conflict/protest CAMEO codes
6. **QuadClass Filter**: Exclude cooperation (classes 1,3); allow conflict (2,4)
7. **Event Age**: Optional max age limit (default 72h)
8. **Source URL**: Optional requirement for article URLs

## Filter Stages

### Stage 1: Ingest (`gdelt_ingest.py`)
- Filters **before** inserting into `gdelt_events` table
- Reduces DB storage and downstream processing
- Tracks `filtered_rows` metric

### Stage 2: Enrichment (`gdelt_enrichment_worker.py`)
- Filters **before** converting to `raw_alerts`
- Additional age/source checks
- Reduces LLM processing costs

## Configuration

### Enable Filtering
```bash
# Required: enable the filter
export GDELT_ENABLE_FILTERS=true
```

### Tune Thresholds (optional)
```bash
# Goldstein scale threshold (default: -5.0, range: -10 to +10)
export GDELT_MIN_GOLDSTEIN=-5.0

# Minimum media mentions (default: 3)
export GDELT_MIN_MENTIONS=3

# Minimum tone (default: -5.0, negative = bad news)
export GDELT_MIN_TONE=-5.0

# Maximum event age in hours (default: 72)
export GDELT_MAX_AGE_HOURS=72

# Require source URLs (default: false)
export GDELT_REQUIRE_SOURCE_URL=false

# Require precise coords, reject (0,0) (default: false)
export GDELT_REQUIRE_PRECISE_COORDS=false
```

## Event Code Whitelist

Only these CAMEO event categories pass the filter:

- **14x**: Protest, demonstration, strikes
- **18x**: Assault, physical violence
- **19x**: Conventional military force, armed conflict
- **20x**: Mass violence, torture, ethnic cleansing

Full list in `gdelt_filters.py` (50+ specific codes)

## Monitoring

### Check Filter Stats
```bash
curl -H "X-API-Key: YOUR_KEY" https://your-app.railway.app/admin/gdelt/filter-stats
```

Response:
```json
{
  "ok": true,
  "filters_enabled": true,
  "filter_config": {
    "min_goldstein": -5.0,
    "min_mentions": 3,
    "min_tone": -5.0,
    "max_age_hours": 72,
    "allowed_event_codes_count": 50,
    "allowed_quad_classes": [2, 4]
  },
  "ingest_metrics": {
    "total_rows_processed": 125000,
    "skipped_rows": 1200,
    "filtered_rows": 98500,
    "successful_ingests": 25300
  }
}
```

### Metrics Explained
- `total_rows_processed`: Total GDELT rows parsed
- `filtered_rows`: Events rejected by filter
- `successful_ingests`: Events inserted to DB
- **Filter rate**: ~79% in example above (98.5k filtered / 125k total)

## Expected Impact

### Before Filtering (default GDELT)
- 15-minute export: ~50,000 events
- Includes: diplomatic statements, cooperation, unverified rumors
- Signal-to-noise: ~10%

### After Filtering (brutal mode)
- 15-minute export: ~5,000-10,000 events (80-90% reduction)
- Only: verified violence, conflict, protests with negative impact
- Signal-to-noise: ~80%

### Cost Savings
- **Storage**: 80% reduction in `gdelt_events` table size
- **LLM processing**: 80% reduction in API calls to Threat Engine
- **Frontend performance**: Fewer alerts = faster map rendering

## Deployment

### Railway
Add environment variable in Railway dashboard:
```
GDELT_ENABLE_FILTERS=true
```

### Deploy
```bash
railway up
```

### Verify
```bash
# Check logs for filter activity
railway logs

# Look for:
# [filter] ACCEPTED: event_id=123, code=190, goldstein=-8.5, mentions=15, tone=-12.3
# [filter] Rejected: goldstein 2.0 > -5.0 (event_id=456)
```

## Tuning Guide

### Too Few Events?
Relax thresholds:
```bash
export GDELT_MIN_GOLDSTEIN=-3.0  # Less negative threshold
export GDELT_MIN_MENTIONS=2       # Fewer sources required
export GDELT_MIN_TONE=-3.0        # Less negative sentiment
```

### Still Too Noisy?
Tighten thresholds:
```bash
export GDELT_MIN_GOLDSTEIN=-7.0   # Only extreme events
export GDELT_MIN_MENTIONS=5        # More sources required
export GDELT_MIN_TONE=-7.0         # Very negative sentiment only
export GDELT_REQUIRE_PRECISE_COORDS=true  # Reject (0,0) centroids
```

### Focus on Recent Events Only
```bash
export GDELT_MAX_AGE_HOURS=24  # Last 24 hours only
```

## Debug Mode

Enable verbose filter logging:
```python
# In gdelt_filters.py, change:
logger.setLevel(logging.DEBUG)
```

## Files Modified

- `gdelt_filters.py` (new): Filter logic and config
- `gdelt_ingest.py`: Stage 1 integration (ingest)
- `gdelt_enrichment_worker.py`: Stage 2 integration (enrichment)
- `main.py`: Added `/admin/gdelt/filter-stats` endpoint

## Testing Locally

```bash
# Enable filters
export GDELT_ENABLE_FILTERS=true
export DATABASE_URL=your_db_url

# Run ingest
python -c "from gdelt_ingest import manual_trigger; print(manual_trigger())"

# Run enrichment
python gdelt_enrichment_worker.py

# Check stats
python -c "from gdelt_filters import get_filter_stats; print(get_filter_stats())"
```

## Rollback

Disable filtering without code changes:
```bash
railway variables set GDELT_ENABLE_FILTERS=false
```

Events will process normally until you re-enable.
