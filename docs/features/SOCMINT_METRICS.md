# SOCMINT Cache Metrics & Logging

## Overview
The SOCMINT subsystem now includes comprehensive cache metrics tracking and enhanced logging to monitor performance and optimize Apify API usage.

## Cache Metrics

### Tracked Metrics
- **hits**: Number of successful cache retrievals (data served from DB)
- **misses**: Number of cache misses requiring fresh scrapes
- **total_requests**: Total cache lookup attempts
- **apify_calls**: Number of fresh Apify actor runs
- **cache_saves**: Number of successful DB persists
- **errors**: Total error count across all operations
- **hit_rate_percent**: Cache hit rate percentage

### Cache TTL
- Default: **2 hours** (120 minutes)
- Configurable per request via `ttl_minutes` parameter
- Reduces redundant scrapes and API quota usage

## API Endpoints

### Get Metrics
```http
GET /api/socmint/metrics
Authorization: Bearer <token>
```

**Response:**
```json
{
  "status": "success",
  "metrics": {
    "hits": 42,
    "misses": 18,
    "total_requests": 60,
    "apify_calls": 18,
    "cache_saves": 18,
    "errors": 0,
    "hit_rate_percent": 70.0
  }
}
```

### Reset Metrics
```http
POST /api/socmint/metrics/reset
Authorization: Bearer <token>
```

**Response:**
```json
{
  "status": "success",
  "message": "Cache metrics reset successfully"
}
```

## Logging Enhancements

### Cache Operations
```
[SOCMINT] Cache hit: instagram/malware_king - age=15m, posts=12
[SOCMINT] Cache miss: facebook/threat.actor (TTL=120m)
[SOCMINT] Starting Instagram scrape: malware_king (limit=10)
[SOCMINT] Instagram scrape successful: malware_king - profile=True, posts=8
[SOCMINT] Persisted instagram for malware_king (profile=True, posts=8)
```

### Enrichment Pipeline
```
[SOCMINT Enrichment] Using cached data: instagram/malware_king
[SOCMINT Enrichment] Cache miss, initiating fresh scrape: facebook/page123
[SOCMINT Enrichment] Completed for alert abc-123: 2 OSINT entries added
```

### Performance Summary
Periodic summary (callable via `log_cache_performance_summary()`):
```
============================================================
📊 SOCMINT CACHE PERFORMANCE SUMMARY
============================================================
Total Cache Requests: 150
Cache Hits: 105
Cache Misses: 45
Hit Rate: 70.0%
Fresh Apify Calls: 45
New Cache Saves: 45
Errors: 0
Cache Efficiency: 70.0% (avoided 105 Apify calls)
============================================================
```

## Integration Examples

### Python Code
```python
from socmint_service import (
    get_cache_metrics, 
    reset_cache_metrics,
    log_cache_performance_summary
)

# Get current metrics
metrics = get_cache_metrics()
print(f"Hit rate: {metrics['hit_rate_percent']}%")

# Log performance summary
log_cache_performance_summary()

# Reset counters (e.g., daily/weekly)
reset_cache_metrics()
```

### Flask Routes
```python
from socmint_service import get_cache_metrics

@app.route('/admin/socmint/stats')
def socmint_stats():
    metrics = get_cache_metrics()
    return render_template('socmint_stats.html', metrics=metrics)
```

## Benefits

### Cost Optimization
- **Reduced API calls**: Cache hit rate of 70%+ saves significant Apify quota
- **Faster response**: Cached data returns in ~100ms vs ~3-5s for fresh scrape
- **Lower quota consumption**: 2-hour TTL balances freshness and efficiency

### Operational Visibility
- **Real-time monitoring**: Track cache performance via metrics endpoint
- **Error tracking**: Isolated error counts for cache, scrape, and persist operations
- **Trend analysis**: Log historical metrics for capacity planning

### Performance Insights
- **Hit rate**: Target >60% for optimal efficiency
- **Apify call reduction**: Each cache hit = 1 avoided API call + 3-5s saved
- **Error rate**: Monitor for scraper blocks or DB issues

## Best Practices

1. **Monitor hit rate**: Aim for >60% hit rate; adjust TTL if too low
2. **Reset periodically**: Reset metrics daily/weekly for trend tracking
3. **Alert on errors**: Set up monitoring for sustained error rates >5%
4. **Log summaries**: Call `log_cache_performance_summary()` hourly in production
5. **Adjust TTL**: Increase TTL for stable profiles, decrease for active threat actors

## Testing

Run SOCMINT test suite:
```bash
python3 run_tests.py  # Full suite
python3 tests/socmint/test_cache_metrics.py  # Metrics only
python3 demo_socmint_metrics.py  # Interactive demo
```

## Troubleshooting

### Low hit rate (<40%)
- Check TTL configuration (may be too short)
- Verify cache persistence is working (check `cache_saves`)
- Review error logs for DB connection issues

### High error rate
- Check Apify token validity
- Review rate limit compliance
- Verify DB connectivity and schema

### Stale data concerns
- Reduce TTL for active threat actors
- Implement selective cache invalidation
- Add `force_refresh` parameter for critical lookups
