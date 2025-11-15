# GDELT Quick Reference

## API Endpoints

```bash
# Get threats near coordinates
curl "https://your-app.railway.app/api/gdelt/threats/nearby?lat=50.45&lon=30.52&radius=100&days=7"

# Get country summary
curl "https://your-app.railway.app/api/gdelt/country/UA?days=30"

# Get trending threats
curl "https://your-app.railway.app/api/gdelt/trending?days=7&min_articles=10"

# Check health
curl "https://your-app.railway.app/admin/gdelt/health"

# Manual trigger (requires API key)
curl -X POST -H "X-API-Key: YOUR_KEY" \
  "https://your-app.railway.app/admin/gdelt/ingest"
```

## Python Usage

```python
from gdelt_query import GDELTQuery

# Location query
threats = GDELTQuery.get_threats_near_location(
    lat=50.4501, lon=30.5234, radius_km=100, days=7
)

# Country summary
summary = GDELTQuery.get_country_summary('UA', days=30)

# Trending
trending = GDELTQuery.get_trending_threats(days=7, min_articles=10)
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     GDELT 2.0 API                           │
│            (15-minute exports, lastupdate.txt)              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              INGESTION LAYER (gdelt_ingest.py)              │
│  • Background daemon thread (15min polling)                 │
│  • Retry logic (3 attempts, 5s backoff)                     │
│  • Defensive parsing (safe_int, safe_float)                 │
│  • Batch processing (1000 rows, ON CONFLICT DO NOTHING)     │
│  • Metrics tracking (gdelt_metrics table)                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              STORAGE (PostgreSQL on Railway)                │
│  • gdelt_events: 61 columns + JSONB raw (1,153 events)     │
│  • gdelt_state: Deduplication tracking                      │
│  • gdelt_metrics: Observability (duration, counts)          │
│  • 9 indexes: date, country, goldstein, quad_class, etc.   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│             QUERY LAYER (gdelt_query.py)                    │
│  • Direct SQL, zero ORM overhead                            │
│  • Haversine distance calculation                           │
│  • Pre-filters: QuadClass 3/4, Goldstein < -5              │
│  • Returns JSON-ready dicts                                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                API ENDPOINTS (main.py)                       │
│  • GET /api/gdelt/threats/nearby                            │
│  • GET /api/gdelt/country/<code>                            │
│  • GET /api/gdelt/trending                                  │
│  • GET /admin/gdelt/health                                  │
│  • POST /admin/gdelt/ingest                                 │
└─────────────────────────────────────────────────────────────┘
```

## Filters Applied by Query Layer

| Function | QuadClass | Goldstein | Articles | Location | Sort |
|----------|-----------|-----------|----------|----------|------|
| get_threats_near_location | 3 or 4 | < -5 | Any | Required | Date DESC, Severity ASC |
| get_country_summary | 3 or 4 | < -5 | Any | Any | Aggregated |
| get_trending_threats | 3 or 4 | < -5 | >= min | Any | Articles DESC, Severity ASC |

## Response Examples

### Nearby Threats
```json
{
  "ok": true,
  "count": 5,
  "threats": [{
    "event_id": "1234567890",
    "date": "20251115",
    "actor1": "MILITARY",
    "actor2": "GOVERNMENT",
    "country": "UA",
    "severity": 9.0,
    "articles": 45,
    "sources": 12,
    "lat": 50.45,
    "lon": 30.52,
    "source_url": "https://...",
    "distance_km": 23.4
  }]
}
```

### Country Summary
```json
{
  "ok": true,
  "country": "UA",
  "period_days": 30,
  "total_events": 156,
  "avg_severity": 8.4,
  "worst_severity": 10.0,
  "unique_actors": 23,
  "total_coverage": 2400,
  "most_recent": "20251115"
}
```

### Health Check
```json
{
  "status": "healthy",
  "last_ingest": "2025-11-15T18:48:10.569857+00:00",
  "last_file": "20251115184500.export.CSV.zip",
  "events_24h": 1153,
  "polling_enabled": true
}
```

## Environment Variables

```bash
GDELT_ENABLED=true                 # Enable background polling
GDELT_POLL_INTERVAL_MIN=15        # Poll every 15 minutes
GDELT_MAX_RETRIES=3               # Retry failed requests 3 times
GDELT_RETRY_BACKOFF_SEC=5         # Wait 5s between retries
```

## Files

| File | Purpose | Lines |
|------|---------|-------|
| gdelt_ingest.py | Production ingestion with polling | 423 |
| gdelt_query.py | High-performance query functions | 203 |
| test_gdelt_hybrid.py | Comprehensive test suite | 180 |
| GDELT_HYBRID_SYSTEM.md | Complete documentation | 300+ |
| main.py | API endpoints (+75 lines) | 2599 |

## Testing

```bash
# Run comprehensive tests
python test_gdelt_hybrid.py

# Test query layer only
python -c "from gdelt_query import GDELTQuery; \
  print(GDELTQuery.get_country_summary('US', 30))"

# Check syntax
python -m py_compile gdelt_query.py
```

## Performance

- Ingestion: ~500 events/sec (batch processing)
- Location query: <100ms (Haversine + indexes)
- Country summary: <50ms (aggregation)
- Trending: <80ms (sorted by coverage)

## Deployment

```bash
# Set environment variables (already done)
railway variables --set GDELT_ENABLED=true

# Deploy
git add .
git commit -m "Add GDELT hybrid query layer"
git push
railway up

# Monitor
railway logs --tail 50
```
