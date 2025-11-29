# Phase 4 – Real-Time Fallback & Proactive Coverage Expansion

Status: IMPLEMENTED (initial manager + tests)
File: `real_time_fallback.py`

## Objectives
1. Automatically reinforce geographic coverage when gaps are detected
2. Reduce advisory gating due to insufficient data
3. Proactively ingest alternative sources for sparse or stale regions
4. Provide auditable attempt history + cooldown logic

## Components
### `CoverageMonitor`
Already tracks sparse/stale locations. We use:
- `get_coverage_gaps(min_alerts_7d=5, max_age_hours=24)`

### `RealTimeFallbackManager`
Responsibilities:
- Inspect current gaps
- Enforce per-location cooldown & max daily attempts
- Select appropriate feeds (country → global fallback)
- Fetch limited items per feed (`feedparser`)
- Filter items referencing the country name
- Record synthetic alerts (confidence heuristic currently 0.35)
- Return structured attempt summaries

### Attempt Lifecycle
```
for gap in coverage_gaps:
    if cooldown/limit allows:
        choose country feeds else global feeds
        fetch entries (bounded)
        filter items referencing country name
        record synthetic alerts into CoverageMonitor
        store FallbackAttempt summary
```

## Configuration Parameters
| Parameter | Default | Purpose |
|-----------|---------|---------|
| `min_alerts_7d` | 5 | Sparse threshold for gap detection |
| `max_age_hours` | 24 | Stale threshold for gap detection |
| `max_concurrent` | 5 | Max gaps processed per trigger |
| `location_cooldown_hours` | 6 | Minimum hours between attempts per location |
| `max_attempts_per_day` | 3 | Upper bound on daily fallback attempts per location |
| `DEFAULT_MAX_ITEMS_PER_FEED` | 15 | Per-feed item cap |

## Public API
```python
from real_time_fallback import get_fallback_manager, perform_realtime_fallback

manager = get_fallback_manager()
attempts = manager.trigger_for_gaps()  # returns list[FallbackAttempt]

# Convenience wrapper:
results = perform_realtime_fallback()  # list[dict]
```

`FallbackAttempt` fields:
- `country, region, issues`
- `feed_type` ("country" or "global")
- `feeds_used` (list of URLs)
- `fetched_items`
- `created_alerts` (synthetic alerts recorded)
- `status` (success | no_match | empty | error | skipped | no_feeds)
- `error` (optional string)
- `timestamp`

## Integration Points
### 1. Scheduled Trigger (Recommended)
Use APScheduler or cron to run every 30–60 minutes.
```python
from real_time_fallback import perform_realtime_fallback

def run_fallback_cycle():
    attempts = perform_realtime_fallback()
    for a in attempts:
        logger.info(f"[FallbackCycle] {a['country']} status={a['status']} created_alerts={a['created_alerts']}")
```

### 2. On-Demand Ops Endpoint
```python
@app.route('/api/fallback/trigger', methods=['POST'])
def trigger_fallback():
    from real_time_fallback import perform_realtime_fallback
    results = perform_realtime_fallback()
    return jsonify({"attempts": results, "count": len(results)})
```

### 3. Dashboard Metrics
Enhance existing coverage dashboard to include:
- Fallback attempts (success vs skipped)
- Synthetic alerts created per country
- Time since last fallback attempt per location
- Ratio: synthetic alerts / organic alerts (watch for imbalance)

## Observability & Guardrails
1. **Cooldown** prevents hammering same location.
2. **Attempt limit** guards against runaway loops on chronic gaps.
3. **Confidence heuristic** (0.35) keeps synthetic alerts clearly marked as low-confidence if later surfaced.
4. **Filtering** ensures at least nominal relevance (title/summary contains country name).
5. Future: Add provenance flag (e.g. `synthetic: true`) to alert schema.

## Future Enhancements (Backlog)
- Add city-level fallback using `LOCAL_FEEDS` when region has specific urban gap.
- Integrate LLM summarization for clusters of synthetic items → single consolidated alert with improved confidence.
- Adaptive confidence scoring based on feed reliability & item freshness.
- Add circuit breaker: disable fallback for a location after N consecutive empty attempts.
- Persist attempt history in DB for multi-process visibility.
- Introduce ML-based relevance classifier instead of simple keyword matching.

## Testing Summary
File: `test_real_time_fallback.py`
Scenarios:
- No gaps → no attempts.
- Sparse country with catalog feed → success + synthetic alerts.
- Missing country → global feed fallback works.
- Cooldown + daily limit prevents repeated attempts.

Run:
```bash
python test_real_time_fallback.py
```

## Deployment Checklist
1. Ensure `feedparser` installed (already used by RSS pipeline).
2. Schedule periodic fallback trigger (cron or APScheduler).
3. Add ops endpoint for manual triggering (optional).
4. Monitor synthetic alert proportion; tune thresholds if >20% of alerts for any country.
5. Plan provenance schema update (Phase 4b) before surfacing synthetic alerts externally.

## Rollback Strategy
- Remove scheduler job / disable endpoint.
- Delete synthetic alerts (identify via future provenance flag) if necessary.
- Reset coverage monitor metrics (`coverage_monitor.get_coverage_monitor().reset_metrics()`).

## Success Metrics
- Reduction in coverage gaps count (weekly). Target: >30% decrease.
- Advisory gating due to insufficient data reduced. Target: <10% of total gating reasons.
- Synthetic alert ratio stable (<20% of total) after 2 weeks.
- Mean time to coverage restoration for sparse regions < 12 hours.

## Quick Start
```python
from real_time_fallback import perform_realtime_fallback
results = perform_realtime_fallback()
print(results)
```

---
Phase 4 base implementation complete. Proceed with provenance and dashboard integration (Phase 4b) when ready.
