# Sentinel AI Unified Intelligence Architecture

## Data Flow Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     INGESTION SOURCES                            │
├─────────────────────────────────────────────────────────────────┤
│  RSS Feeds          ACLED API         GDELT v2.0                │
│  (keyword-filtered) (curated conflict) (global events)          │
└────────┬────────────────┬────────────────┬──────────────────────┘
         │                │                │
         └────────────────┴────────────────┘
                          │
                   ┌──────▼──────┐
                   │ raw_alerts  │ ◄─── Single ingestion table
                   └──────┬──────┘      (minimal schema)
                          │
                ┌─────────▼──────────┐
                │  THREAT ENGINE     │  ◄─── Unified enrichment
                │  (threat_scorer,   │      pipeline
                │   enrichment_stages,│
                │   risk_shared)     │
                └─────────┬──────────┘
                          │
            ┌─────────────┴─────────────┐
            │   SOCMINT Enrichment      │  ◄─── Social intelligence
            │   (enrichment_stages)     │      augmentation
            └─────────────┬─────────────┘
                          │
                   ┌──────▼──────┐
                   │   alerts    │  ◄─── Final enriched intel
                   │  (full schema)│     (scored, categorized,
                   └──────┬──────┘      embedded, SOCMINT)
                          │
                   ┌──────▼──────┐
                   │   ADVISOR   │  ◄─── User-facing intelligence
                   └─────────────┘
```

## Component Responsibilities

### Ingestion Layer (→ raw_alerts)

**RSS Processor** (`rss_processor.py`)
- **Trigger**: Cron every 15 minutes
- **Source**: RSS feeds (feeds_catalog.py)
- **Filtering**: Keyword co-occurrence matching (risk_shared + threat_keywords.json)
- **Output**: raw_alerts with location extraction, basic validation
- **Key Fields**: uuid, title, summary, published, source, latitude, longitude, tags

**ACLED Collector** (`acled_collector.py`)
- **Trigger**: Cron daily at 01:15 UTC
- **Source**: ACLED API (OAuth, curated conflict/political violence data)
- **Filtering**: None (pre-curated upstream)
- **Output**: raw_alerts with rich metadata tags
- **Key Fields**: Same as RSS + actor1/actor2, fatalities, admin levels

**GDELT Enrichment Worker** (`gdelt_enrichment_worker.py`)
- **Trigger**: Cron every 10 minutes
- **Source**: gdelt_events table (populated by gdelt_ingest.py background thread)
- **Filtering**: quad_class IN (3,4) + has coordinates (conflict events only)
- **Output**: raw_alerts with Goldstein/tone metrics in tags
- **Note**: gdelt_ingest.py polls GDELT v2 every 15 min (GDELT_ENABLED=true)

### Enrichment Layer (raw_alerts → alerts)

**Threat Engine** (`threat_engine.py`)
- **Trigger**: Cron every 15 minutes (offset 7,22,37,52)
- **Input**: raw_alerts (all sources unified)
- **Processing Pipeline**:
  1. **Normalization**: Clean HTML, dedupe via vector embeddings
  2. **Keyword Matching**: Risk domains, categories (threat_scorer)
  3. **Location Enhancement**: Geocoding cache, reverse country lookup
  4. **Threat Scoring**: Multi-factor scoring (threat_scorer.py)
  5. **Risk Analysis**: Sentiment, forecast, legal/cyber/environmental risks
  6. **SOCMINT Enrichment**: Social media handle extraction + profile enrichment
  7. **Domain Detection**: Canonical taxonomy (risk_shared)
  8. **Confidence Calculation**: Multi-source verification, data quality
- **Output**: alerts (full schema with 40+ enriched fields)

**SOCMINT Integration** (`enrichment_stages.py` → `socmint_service.py`)
- **Trigger**: Embedded in Threat Engine pipeline
- **Function**: Extract social handles (Twitter, Instagram, Facebook, Telegram, etc.)
- **Enrichment**: Profile metadata, follower counts, verification status
- **Storage**: socmint_profiles table + alert.threat_score_components.socmint
- **Caching**: Persistent to avoid re-scraping (cost optimization)

### Query Layer (alerts → insights)

**Advisor** (`advisor.py`, `chat_handler.py`)
- **Input**: User queries + profile context
- **Data**: alerts table (enriched intelligence)
- **Processing**: LLM-powered analysis with embedded risk context
- **Output**: Tactical advisories with threat playbooks, recommendations

**Analytics Endpoints** (`main.py`)
- `/analytics/timeline`: Time-series incident aggregation
- `/analytics/statistics`: Threat level summaries, top countries
- `/alerts/latest`: GeoJSON features with plan-based caps

## Schema Comparison

### raw_alerts (Ingestion)
```sql
uuid TEXT PRIMARY KEY
published TIMESTAMPTZ
source TEXT (rss|acled|gdelt)
source_kind TEXT (feed|intelligence)
source_tag TEXT (country:XX or local:City,Country)
title TEXT
summary TEXT
link TEXT
region TEXT
country TEXT
city TEXT
latitude NUMERIC
longitude NUMERIC
tags JSONB -- Source-specific metadata
```

### alerts (Enriched)
```sql
-- All raw_alerts fields PLUS:
category TEXT (conflict|cyber|...)
subcategory TEXT
threat_level TEXT (low|medium|high|critical)
threat_label TEXT
score NUMERIC (0-100)
confidence NUMERIC (0-1)
gpt_summary TEXT -- LLM-generated tactical summary
reasoning TEXT
sentiment TEXT
forecast TEXT
legal_risk TEXT
cyber_ot_risk TEXT
environmental_epidemic_risk TEXT
domains TEXT[] -- [political_instability, armed_conflict, ...]
early_warning_indicators JSONB
threat_score_components JSONB -- {socmint: {...}, keyword_match: {...}}
embedding VECTOR(1536) -- For semantic dedup/search
model_used TEXT
trend_direction TEXT
anomaly_flag BOOLEAN
-- + 10 more analytics/enrichment fields
```

## Cron Schedule (railway.toml)

```toml
# Ingestion (→ raw_alerts)
rss-ingest:      */15 * * * *  (every 15 min)
gdelt-enrich:    */10 * * * *  (every 10 min)
acled-daily:     15 1 * * *    (daily 01:15 UTC)

# Enrichment (raw_alerts → alerts)
engine-enrich:   7,22,37,52 * * * *  (every 15 min, offset from ingestion)

# Maintenance
retention-cleanup: 0 */6 * * *  (every 6 hours)
daily-vacuum:      0 2 * * *    (daily 02:00 UTC)
```

## Key Dependencies

**Keyword/Risk Systems**:
- `risk_shared.py`: Canonical taxonomy, domain detection, keyword matching
- `threat_keywords.json`: Threat-specific keyword lists
- `keywords_loader.py`: Unified keyword management

**Scoring**:
- `threat_scorer.py`: Multi-factor threat scoring (keywords, mentions, patterns)
- `enrichment_stages.py`: Modular enrichment pipeline (12+ stages)

**LLM Routing**:
- `llm_router.py`: Task-aware model selection (Moonshot/Grok/DeepSeek/OpenAI)
- `llm_rate_limiter.py`: Circuit breaker + quota management

**Social Intelligence**:
- `socmint_service.py`: Profile enrichment (Apify scrapers)
- `socmint_routes.py`: API endpoints for direct profile queries

## Environment Variables

### Required
- `DATABASE_URL`: PostgreSQL connection string
- `ADMIN_API_KEY`: Admin endpoint authentication

### LLM (at least one required)
- `XAI_API_KEY` (Grok)
- `MOONSHOT_API_KEY` (Kimi)
- `DEEPSEEK_API_KEY`
- `OPENAI_API_KEY`

### ACLED (optional, required for daily collection)
- `ACLED_EMAIL`: ACLED account email
- `ACLED_PASSWORD`: ACLED account password

### GDELT
- `GDELT_ENABLED=true`: Enable background polling (default: false)
- `GDELT_POLL_INTERVAL_MIN=15`: Ingest frequency (default: 15)

### Tuning
- `RSS_BATCH_LIMIT=400`: Max alerts per RSS run
- `ENGINE_BATCH_LIMIT=1000`: Max raw_alerts processed per run
- `GDELT_ENRICHMENT_BATCH_SIZE=1000`: GDELT events per batch
- `ALERT_RETENTION_DAYS=90`: Data retention window

## Migration Notes (Nov 2025)

### GDELT Flow Change
**Before**: gdelt_events → gdelt_enrichment_worker → alerts (direct insert, no SOCMINT)
**After**: gdelt_events → gdelt_enrichment_worker → raw_alerts → Threat Engine → alerts (unified enrichment)

**Benefits**:
- SOCMINT augmentation for GDELT events
- Consistent scoring across all sources
- Vector deduplication (prevents duplicate GDELT/RSS overlap)
- Unified domain taxonomy
- Embedding-based semantic search

### Cron Consolidation
- **Removed**: Railway dashboard cron jobs (duplicates)
- **Active**: railway.toml cron entries (authoritative source)
- **Action Required**: Manually disable old crons in Railway Settings → Cron Jobs

## Verification Steps

### 1. Ingestion Health
```bash
# Check raw_alerts recent inserts by source
psql $DATABASE_URL -c "
SELECT source, COUNT(*) as count, MAX(published) as latest
FROM raw_alerts
WHERE published > NOW() - INTERVAL '1 hour'
GROUP BY source;"
```

### 2. Enrichment Pipeline
```bash
# Check raw_alerts → alerts conversion rate
psql $DATABASE_URL -c "
SELECT 
  (SELECT COUNT(*) FROM raw_alerts WHERE published > NOW() - INTERVAL '1 day') as raw,
  (SELECT COUNT(*) FROM alerts WHERE published > NOW() - INTERVAL '1 day') as enriched;"
```

### 3. SOCMINT Coverage
```bash
# Check alerts with SOCMINT enrichment
psql $DATABASE_URL -c "
SELECT COUNT(*) 
FROM alerts 
WHERE threat_score_components->>'socmint' IS NOT NULL
  AND published > NOW() - INTERVAL '1 day';"
```

### 4. Cron Execution Logs
```bash
# Via Railway CLI
railway logs --filter "railway_cron"
```

## API Endpoints

### Admin Triggers (X-API-Key required)
- `POST /admin/gdelt/enrich?batch_size=1000`: Manual GDELT batch
- `POST /admin/acled/run?days_back=1`: Manual ACLED fetch
- `POST /rss/run`: Manual RSS ingestion
- `POST /engine/run`: Manual enrichment cycle

### Analytics (Auth required)
- `GET /analytics/timeline?days=30`: Incident timeline
- `GET /analytics/statistics`: Threat summary stats
- `GET /alerts/latest?limit=50&days=7`: Recent enriched alerts

### Advisory
- `POST /chat`: LLM-powered threat advisory (quota-limited)
- `POST /api/travel-risk/assess`: Location-specific risk assessment

## Future Enhancements

1. **Adaptive Scheduling**: Adjust cron frequency based on ingestion velocity
2. **Source Priority Weighting**: Multi-source verification score boost
3. **Real-time Fallback**: On-demand ingestion for coverage gaps
4. **SOCMINT Expansion**: LinkedIn, YouTube, Reddit enrichment
5. **Embedding Search**: Semantic threat similarity API
6. **Streaming Ingestion**: WebSocket feeds for ultra-low latency sources

---
**Last Updated**: November 16, 2025
**Architecture Version**: v2.0 (Unified Pipeline)
