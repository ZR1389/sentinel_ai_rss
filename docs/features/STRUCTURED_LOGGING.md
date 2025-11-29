# Structured Logging for Sentinel AI

## Overview

Sentinel AI now uses structured logging with JSON output for production observability. This enables better monitoring with tools like Datadog, New Relic, and CloudWatch.

## Features

### ✅ Automatic Environment Detection
- **Development**: Human-readable console output
- **Production**: JSON structured logging (auto-detected via `RAILWAY_ENVIRONMENT_NAME`)
- **Manual Override**: Use `STRUCTURED_LOGGING=true` to force JSON output

### ✅ Service Context
- Every log entry includes `service` field for multi-service deployments
- Service names: `sentinel-api`, `retention-worker`, etc.

### ✅ Metrics Logging
- Pre-built metrics functions for common operations
- Consistent field naming across the application
- Performance tracking with duration measurements

### ✅ Enhanced Error Tracking
- Structured error context with full stack traces
- Request-specific information for API errors
- Database operation error details

## Usage Examples

### Basic Structured Logging
```python
from logging_config import get_logger

logger = get_logger("module_name")

# Simple structured log
logger.info("user_authenticated", 
           user_email="user@example.com", 
           session_id="abc123",
           duration_ms=145)

# Error with context
logger.error("database_connection_failed",
            error=str(e),
            host="localhost",
            database="sentinel",
            retry_count=3)
```

### Metrics Logging
```python
from logging_config import get_metrics_logger

metrics = get_metrics_logger("threat_engine")

# Alert processing metrics
metrics.alert_processed(
    alert_uuid="alert-123",
    score=0.85,
    duration_ms=1523,
    cache_hit=False,
    location_confidence=0.92
)

# Database operation metrics
metrics.database_operation(
    operation="insert",
    table="alerts",
    duration_ms=245,
    rows_affected=15
)

# API request metrics  
metrics.api_request(
    endpoint="/api/alerts",
    method="POST", 
    status_code=200,
    duration_ms=1834,
    user_email="user@example.com"
)

# LLM request metrics
metrics.llm_request(
    provider="openai",
    model="gpt-4",
    duration_ms=2156,
    prompt_tokens=1024,
    completion_tokens=512,
    cache_hit=False
)
```

### Alert Enrichment Example
```python
# In threat_engine.py
start_time = datetime.now()
# ... processing logic ...
duration = (datetime.now() - start_time).total_seconds() * 1000

metrics.alert_enriched(
    alert_uuid=alert.get("uuid"),
    confidence=alert.get("confidence"), 
    duration_ms=round(duration, 2),
    location_confidence=alert.get("location_confidence"),
    cache_hit=False
)
```

## JSON Output Format

Production logs output clean JSON for parsing:

```json
{
  "alert_uuid": "alert-abc123",
  "score": 0.85,
  "duration_ms": 1523,
  "cache_hit": false,
  "location_confidence": 0.92,
  "event": "alert_processed",
  "service": "sentinel-api", 
  "level": "info",
  "logger": "threat_engine",
  "timestamp": "2025-11-12T07:25:45.379708Z"
}
```

## Configuration

### Environment Variables
- `STRUCTURED_LOGGING`: Set to `true` for JSON output (auto-enabled in Railway)
- `LOG_LEVEL`: Set log level (`DEBUG`, `INFO`, `WARN`, `ERROR`)
- `RAILWAY_ENVIRONMENT_NAME`: Auto-detected Railway environment

### Production Setup
Structured logging is automatically enabled when deployed to Railway. No additional configuration needed.

### Development Setup  
For local development with JSON logging:
```bash
export STRUCTURED_LOGGING=true
python main.py
```

## Monitoring Integration

### Datadog
```yaml
# datadog.yaml
logs:
  - type: file
    path: "/app/logs/*.log"
    service: sentinel-api
    source: python
    sourcecategory: sourcecode
```

### New Relic
```ini
# newrelic.ini
[newrelic]
license_key = YOUR_LICENSE_KEY
app_name = Sentinel AI
```

### CloudWatch
Logs are automatically structured and searchable in CloudWatch when deployed to Railway.

## Key Metrics to Monitor

### Performance Metrics
- `alert_processed`: Alert processing performance
- `alert_enriched`: Alert enrichment quality and speed
- `database_operation`: Database operation performance
- `llm_request`: LLM API performance and costs

### Business Metrics
- Alert processing volume
- User activity patterns
- API endpoint usage
- Error rates by component

### System Health
- Database connectivity
- LLM API availability  
- Cache hit rates
- Background job performance

## Migration Notes

### Updated Modules
- ✅ `main.py` - API request logging and error handling
- ✅ `threat_engine.py` - Alert processing metrics
- ✅ `rss_processor.py` - RSS feed processing metrics
- ✅ `retention_worker.py` - Data retention metrics

### Backwards Compatibility
- Standard Python logging still works
- Gradual migration supported
- No breaking changes to existing functionality

## Benefits

### 🔍 **Better Debugging**
- Searchable structured logs
- Request correlation
- Performance bottleneck identification

### 📊 **Production Monitoring**
- Real-time alert processing metrics
- Database performance tracking
- LLM usage and cost monitoring

### 🚨 **Alert System**
- Automated error detection
- Performance threshold monitoring
- System health dashboards

### 📈 **Analytics**
- User behavior analysis
- System usage patterns
- Capacity planning data
