"""
Sentinel AI System Architecture & Configuration Analysis
========================================================

IMMEDIATE QUESTIONS ANSWERED:

## 1. DATABASE SCHEMA

### ALERTS TABLE (Enriched/Final)
```sql
CREATE TABLE public.alerts (
    id integer NOT NULL,
    uuid text NOT NULL,
    title text,
    summary text,
    link text,
    source text,
    published timestamp without time zone,
    region text,
    country text,
    city text,
    latitude numeric,
    longitude numeric,
    category text,
    subcategory text,
    score text,
    label text,
    confidence text,
    domains jsonb DEFAULT '[]'::jsonb,
    sources jsonb DEFAULT '[]'::jsonb,
    baseline_ratio numeric,
    trend_direction text,
    incident_count_30d integer DEFAULT 0,
    anomaly_flag boolean DEFAULT false,
    future_risk_probability text,
    cluster_id text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    gpt_summary text,
    en_snippet text,
    language text,
    kw_match jsonb DEFAULT '[]'::jsonb,
    sentiment text,
    threat_type text,
    threat_level text,
    threat_label text,
    reasoning text,
    forecast text,
    legal_risk text,
    cyber_ot_risk text,
    environmental_epidemic_risk text,
    trend_score text,
    trend_score_msg text,
    is_anomaly boolean DEFAULT false,
    early_warning_indicators jsonb DEFAULT '[]'::jsonb,
    series_id text,
    incident_series text,
    historical_context text,
    recent_count_7d integer DEFAULT 0,
    baseline_avg_7d numeric,
    reports_analyzed integer DEFAULT 1,
    category_confidence double precision,
    review_flag boolean DEFAULT false,
    review_notes text,
    ingested_at timestamp without time zone DEFAULT now(),
    model_used text,
    keyword_weight text,
    tags text[]
);
```

**Constraints:**
- PRIMARY KEY: id
- UNIQUE: uuid

**Indexes:**
- idx_alerts_category (category)
- idx_alerts_city (city)
- idx_alerts_country (country)
- idx_alerts_created (created_at)
- idx_alerts_ingested_at (ingested_at)
- idx_alerts_published (published)
- idx_alerts_region_country (region, country)
- idx_alerts_score (score)
- idx_alerts_tags (tags) - GIN index for JSONB
- idx_alerts_uuid (uuid)

### RAW_ALERTS TABLE (Pre-enrichment)
```sql
CREATE TABLE public.raw_alerts (
    id integer NOT NULL,
    uuid text NOT NULL,
    title text,
    summary text,
    en_snippet text,
    link text,
    source text,
    published timestamp without time zone,
    tags jsonb DEFAULT '[]'::jsonb,
    region text,
    country text,
    city text,
    language text,
    latitude numeric,
    longitude numeric,
    fetched_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now(),
    gpt_summary text,
    kw_match jsonb DEFAULT '[]'::jsonb,
    ingested_at timestamp without time zone DEFAULT now(),
    source_tag text,
    source_kind text,
    source_priority integer
);
```

**Constraints:**
- PRIMARY KEY: id
- UNIQUE: uuid

**Indexes:**
- idx_raw_alerts_city (city)
- idx_raw_alerts_country (country)
- idx_raw_alerts_created (created_at)
- idx_raw_alerts_published (published)
- idx_raw_alerts_uuid (uuid)

## 2. EXTERNAL CLIENTS STATUS

### XAI/Grok Client: ✅ IMPLEMENTED
```python
# File: xai_client.py
def grok_chat(messages, model=GROK_MODEL, temperature=TEMPERATURE, timeout=15):
    """Production-ready Grok client with timeout support"""
```

**Status:** ✅ Production-ready
**Fallback:** Fast 15s timeout for quick failover
**Model:** grok-3-mini (configurable via GROK_MODEL env)
**API:** X.AI SDK integration

### OpenAI Client: ✅ IMPLEMENTED
```python
# File: openai_client_wrapper.py
def openai_chat(messages, temperature=DEFAULT_TEMP, model=DEFAULT_MODEL, timeout=20):
    """Production-ready OpenAI client with timeout support"""
```

**Status:** ✅ Production-ready
**Model:** gpt-4o-mini (default, configurable)
**Timeout:** 20s for fast failover
**Rate Limits:** Not explicitly configured (using OpenAI defaults)

## 3. DB_UTILS FUNCTIONS: ✅ ALL IMPLEMENTED

### Core Functions Available:
```python
def fetch_raw_alerts_from_db(region=None, country=None, city=None, limit=1000):
    """✅ IMPLEMENTED - Returns recent raw alerts for enrichment"""

def save_alerts_to_db(alerts: List[Dict[str, Any]]) -> int:
    """✅ IMPLEMENTED - Bulk upsert into alerts table"""

def fetch_past_incidents(region=None, country=None, days=30):
    """✅ IMPLEMENTED - Historical incident analysis"""

def save_region_trend(region: str, trend_data: Dict):
    """✅ IMPLEMENTED - Regional trend persistence"""
```

### Connection Pooling: ✅ IMPLEMENTED
- **Pool Type:** ThreadedConnectionPool (psycopg2)
- **Min Connections:** 1 (configurable via DB_POOL_MIN_SIZE)
- **Max Connections:** 20 (configurable via DB_POOL_MAX_SIZE)
- **Auto-cleanup:** atexit handler registered

## 4. OPENAI EMBEDDINGS & RATE LIMITS

### Current Status: ⚠️ BASIC IMPLEMENTATION
- **Embeddings:** Used only in translation_utils.py
- **Rate Limits:** No explicit rate limiting configured
- **Quota Management:** Not implemented
- **Fallback:** Basic error handling only

### Recommendation: NEEDS ENHANCEMENT
```python
# Missing: Proper rate limiting for embeddings
# Missing: Quota monitoring
# Missing: Exponential backoff for API errors
```

## 5. ALERT SCHEMA STRUCTURE

### Raw Alert Dictionary (Pre-enrichment):
```python
{
    "uuid": "string",           # GUARANTEED (auto-generated if missing)
    "title": "string",          # GUARANTEED from RSS
    "summary": "string",        # GUARANTEED from RSS
    "en_snippet": "string",     # OPTIONAL (translated summary)
    "link": "string",           # GUARANTEED from RSS
    "source": "string",         # GUARANTEED (RSS feed URL)
    "published": "datetime",    # GUARANTEED from RSS
    "tags": ["string"],         # OPTIONAL (JSONB array)
    "region": "string",         # OPTIONAL (extracted)
    "country": "string",        # OPTIONAL (extracted)
    "city": "string",           # OPTIONAL (extracted)
    "language": "string",       # OPTIONAL (detected)
    "latitude": "numeric",      # OPTIONAL (geocoded)
    "longitude": "numeric",     # OPTIONAL (geocoded)
    "source_tag": "string",     # OPTIONAL (feed classification)
    "source_kind": "string",    # OPTIONAL (feed type)
    "source_priority": "int"    # OPTIONAL (feed priority)
}
```

### Enriched Alert Dictionary (Post-processing):
Includes all raw_alert fields PLUS:
```python
{
    "category": "string",               # Threat category
    "category_confidence": "float",     # ML confidence
    "threat_level": "string",           # Risk level
    "threat_label": "string",           # Classification
    "score": "string",                  # Severity score
    "confidence": "string",             # Overall confidence
    "reasoning": "string",              # LLM reasoning
    "sentiment": "string",              # Sentiment analysis
    "forecast": "string",               # Trend forecast
    "domains": ["string"],              # Threat domains (JSONB)
    "incident_count_30d": "int",        # Historical context
    "baseline_ratio": "numeric",        # Anomaly detection
    "trend_direction": "string",        # Trend analysis
    "anomaly_flag": "boolean",          # Anomaly flag
    "cluster_id": "string",             # Event clustering
    "early_warning_indicators": [],     # Future risk (JSONB)
    # ... additional enrichment fields
}
```

## 6. PERFORMANCE TARGETS & SLA

### Current Configuration (from analysis):
```
Web Workers: Gunicorn + Gevent
- Bind: 0.0.0.0:8080
- Timeout: 300s
- Worker Class: gevent
- Worker Connections: 100

Background Processes:
- worker: scheduler.py
- notify: scheduler_notify.py
```

### Estimated Throughput:
- **Concurrent Connections:** 100 (Gevent)
- **Database Pool:** 20 max connections
- **LLM Timeout:** 15-20s per request
- **Target Alerts/Day:** ~10,000-50,000 (estimated)

### Missing SLA Definitions:
⚠️ **No explicit SLA configured for:**
- Alert enrichment latency
- API response times
- Throughput guarantees

## 7. DEPLOYMENT ARCHITECTURE

### Platform: 🚀 RAILWAY (Primary)
**Evidence:**
- Procfile with gunicorn configuration
- PostgreSQL database URL pattern
- Environment-based configuration

### Architecture: 📊 SINGLE INSTANCE
**Evidence:**
- Single web process
- Shared database connection pool
- No multi-node configuration detected

### Infrastructure Stack:
```
Frontend: Flask + Gunicorn
Workers: Gevent (async)
Database: PostgreSQL 17.6
Caching: Redis (inferred from sessions)
Processing: Background workers (scheduler.py)
```

### Environment Variables Required:
```bash
# Database
DATABASE_URL=postgresql://...
DB_POOL_MIN_SIZE=1
DB_POOL_MAX_SIZE=20

# LLM APIs
GROK_API_KEY=...
OPENAI_API_KEY=...
MOONSHOT_API_KEY=...
DEEPSEEK_API_KEY=...

# Models
GROK_MODEL=grok-3-mini
OPENAI_MODEL=gpt-4o-mini

# Timeouts
GROK_TEMPERATURE=0.3
OPENAI_TEMPERATURE=0.4
```

## 8. RECOMMENDATIONS FOR IMMEDIATE IMPROVEMENTS

### HIGH PRIORITY:
1. **Rate Limiting:** Implement proper OpenAI API rate limiting
2. **SLA Definition:** Set explicit latency/throughput targets
3. **Monitoring:** Add metrics for alert processing pipeline
4. **Error Handling:** Enhanced fallback logic for LLM failures

### MEDIUM PRIORITY:
1. **Caching:** Implement alert enrichment caching
2. **Scaling:** Multi-worker deployment consideration
3. **Backup:** Database backup strategy
4. **Security:** API key rotation strategy

This analysis provides the complete system architecture overview.
All major components are implemented and production-ready with
the noted recommendations for enhancement.
"""
