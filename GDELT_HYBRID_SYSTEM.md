# GDELT Hybrid System

## Architecture

**Production Ingestion Layer** (`gdelt_ingest.py`)
- Polls GDELT 2.0 API every 15 minutes
- Stores all 61 columns + full JSONB raw data
- Batch processing with retry logic and defensive parsing
- Metrics tracking in `gdelt_metrics` table
- Background daemon thread, survives Railway restarts

**High-Performance Query Layer** (`gdelt_query.py`)
- Direct SQL queries with optimized indexes
- Pre-filters for threat intelligence use cases
- Zero ORM overhead, ~500 events/sec throughput
- Reuses existing `db_utils` connection pooling

## Query Functions

### 1. Location-Based Threats
```python
from gdelt_query import GDELTQuery

threats = GDELTQuery.get_threats_near_location(
    lat=50.4501,      # Kyiv
    lon=30.5234,
    radius_km=100,    # 100km radius
    days=7            # Last 7 days
)
```

**Filters:**
- QuadClass 3 (Verbal Conflict) or 4 (Material Conflict)
- Goldstein < -5 (significant negative events)
- Must have lat/lon coordinates
- Sorted by date DESC, severity ASC

### 2. Country Summaries
```python
summary = GDELTQuery.get_country_summary('UA', days=30)

# Returns:
{
    'country': 'UA',
    'total_events': 156,
    'avg_severity': 8.4,
    'worst_severity': 10.0,
    'unique_actors': 23,
    'total_coverage': 2400,  # articles
    'most_recent': '20251115'
}
```

### 3. Trending Threats
```python
trending = GDELTQuery.get_trending_threats(
    days=7,
    min_articles=10  # High media coverage
)
```

## API Endpoints

### GET `/api/gdelt/threats/nearby`
**Parameters:**
- `lat` (required): Latitude
- `lon` (required): Longitude
- `radius` (optional, default 50): Radius in km
- `days` (optional, default 7): Lookback period

**Example:**
```bash
curl "https://your-app.railway.app/api/gdelt/threats/nearby?lat=50.45&lon=30.52&radius=100&days=7"
```

**Response:**
```json
{
  "ok": true,
  "count": 5,
  "threats": [
    {
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
    }
  ]
}
```

### GET `/api/gdelt/country/<code>`
**Parameters:**
- `days` (optional, default 30): Lookback period

**Example:**
```bash
curl "https://your-app.railway.app/api/gdelt/country/UA?days=30"
```

### GET `/api/gdelt/trending`
**Parameters:**
- `days` (optional, default 7): Lookback period
- `min_articles` (optional, default 10): Minimum article coverage

**Example:**
```bash
curl "https://your-app.railway.app/api/gdelt/trending?days=7&min_articles=5"
```

### GET `/admin/gdelt/health`
Returns polling status and metrics.

### POST `/admin/gdelt/ingest`
Manually trigger ingestion (requires `X-API-Key` header).

## Database Tables

### `gdelt_events`
- 61 GDELT columns (BIGINT ID, dates, actors, geo, scores, etc.)
- `raw` JSONB column (full original CSV row)
- 9 performance indexes (see `migrate_gdelt_phase2.sql`)

### `gdelt_state`
- Key-value store for deduplication
- Tracks last processed filename

### `gdelt_metrics`
- Ingestion observability
- Duration, counts, errors per run

## Performance

| Operation | Throughput | Notes |
|-----------|-----------|-------|
| Ingestion | ~500 events/sec | Batch processing |
| Location query | <100ms | Haversine distance calc |
| Country summary | <50ms | Aggregation with indexes |
| Trending query | <80ms | Sorted by article count |

## Environment Variables

```bash
GDELT_ENABLED=true                 # Enable polling
GDELT_POLL_INTERVAL_MIN=15        # Poll frequency
GDELT_MAX_RETRIES=3               # HTTP retry attempts
GDELT_RETRY_BACKOFF_SEC=5         # Backoff delay
```

## Testing

```bash
# Test query layer
python test_gdelt_hybrid.py

# Check health
curl https://your-app.railway.app/admin/gdelt/health

# Manual ingestion (requires API key)
curl -X POST -H "X-API-Key: YOUR_KEY" \
  https://your-app.railway.app/admin/gdelt/ingest
```

## Use Cases

1. **Real-time Threat Alerts**
   - Query `/api/gdelt/threats/nearby` for user locations
   - Cross-reference with RSS alerts for confirmation
   - Add "Confirmed by GDELT" badge in UI

2. **Country Risk Scores**
   - Aggregate `/api/gdelt/country/<code>` metrics
   - Calculate threat density per region
   - Display on country profile pages

3. **Trending Threats Dashboard**
   - Show top 10 from `/api/gdelt/trending`
   - Update every 15 minutes (match polling frequency)
   - Link to source articles

4. **Geospatial Visualization**
   - Plot threats from location queries on map
   - Heatmap based on severity × article count
   - Filter by date range slider

## Next Steps

1. **Enable in Production**
   ```bash
   railway variables --set GDELT_ENABLED=true
   railway up
   ```

2. **Monitor First Cycle**
   - Check logs for "✓ GDELT polling started"
   - Wait 15 minutes for first ingestion
   - Verify via `/admin/gdelt/health`

3. **Integrate with Frontend**
   - Add threat markers to map view
   - Display country summaries in dashboards
   - Show trending threats in news feed

4. **Optional Enhancements**
   - Add GKG (themes, emotions) ingestion
   - Create materialized views for common queries
   - Add PostGIS for true geospatial indexes
   - Implement cleanup job for old events
