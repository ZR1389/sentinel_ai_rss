# Railway Deployment Guide for Sentinel AI

## Health Check Endpoint Setup

### Quick Deploy to Railway

1. **Connect Repository to Railway:**
   ```bash
   # In Railway Dashboard
   # → New Project → Deploy from GitHub → Select sentinel_ai_rss repo
   ```

2. **Configure Environment Variables:**
   ```bash
   # Required
   DATABASE_URL=postgresql://...
   OPENAI_API_KEY=sk-...    # At least one LLM provider
   
   # Optional
   XAI_API_KEY=xai-...
   DEEPSEEK_API_KEY=...
   REDIS_URL=redis://...
   PORT=8080                # Railway auto-sets this
   ```

3. **Set Health Check Path:**
   ```bash
   # In Railway Dashboard → Settings → Health Check
   Health Check Path: /health
   Health Check Timeout: 30s
   ```

4. **Deploy Commands:**
   ```bash
   # RECOMMENDED: FastAPI health server (high performance)
   uvicorn health_check:app --host 0.0.0.0 --port $PORT
   
   # Alternative: Main app with health (full application)
   gunicorn main:app --bind 0.0.0.0:$PORT --timeout 300
   
   # Testing: Health server only (Flask fallback)
   python health_server.py
   ```

### Health Check Endpoints

| Endpoint | Purpose | Response Time |
|----------|---------|---------------|
| `/health` | Full system check | ~2-5s |
| `/health/quick` | Database only | ~100ms |
| `/ping` | Simple liveness | ~10ms |

### Expected Health Check Response

**Healthy System:**
```json
{
  "status": "healthy",
  "timestamp": "2025-11-12T04:24:37.696Z",
  "version": "abc123...",
  "environment": "production",
  "issues": [],
  "checks": {
    "database": {"connected": true, "alert_count": 1337},
    "llm": {"any_available": true},
    "vector_system": {"system_ready": true, "keywords_count": 395},
    "cache": {"available": true}
  }
}
```

**Unhealthy System:**
```json
{
  "status": "unhealthy", 
  "issues": [
    "Database connection failed: connection timeout",
    "No LLM providers configured or available"
  ],
  "checks": {...}
}
```

### Railway Zero-Downtime Deployment

1. **Automatic Health Checks:**
   - Railway pings `/health` every 30s
   - New deployment waits for health check to pass
   - Old version kept running until new version is healthy
   - Traffic switched only after health check succeeds

2. **Deployment Process:**
   ```
   Build new container → Health check passes → Switch traffic → Shut down old container
   ```

3. **Rollback on Failure:**
   ```
   Build new container → Health check fails → Keep old container → Alert developers
   ```

### Monitoring and Alerts

**Status Codes:**
- `200`: System healthy or degraded but functional
- `503`: System unhealthy, should not receive traffic  
- `500`: Health check system failure

**Key Metrics to Monitor:**
- Database connection pool health
- Alert processing pipeline status
- LLM API availability  
- Vector system operational status
- Keyword loading success

### Troubleshooting

**Common Issues:**

1. **Database Connection Fails:**
   ```bash
   # Check DATABASE_URL format
   # Verify database is accessible from Railway
   # Check connection pool settings
   ```

2. **LLM APIs Unavailable:**
   ```bash
   # Verify at least one API key is set
   # Check API quota/rate limits
   # Test API connectivity
   ```

3. **Vector System Not Ready:**
   ```bash
   # Check config/threat_keywords.json exists
   # Verify pgvector functions installed
   # Check database migration status
   ```

4. **Memory/Performance Issues:**
   ```bash
   # Monitor /health response times
   # Check alert_count for database growth
   # Review connection pool metrics
   ```

### Production Recommendations

1. **Use Multiple Health Endpoints:**
   ```bash
   # Railway health check: /health/quick (fast)
   # External monitoring: /health (comprehensive)
   # Load balancer: /ping (fastest)
   ```

2. **Set Appropriate Timeouts:**
   ```bash
   # Railway health check timeout: 30s
   # Database connection timeout: 10s  
   # LLM API timeout: 5s
   ```

3. **Configure Graceful Degradation:**
   ```bash
   # Cache failures: non-critical
   # LLM failures: use fallback scoring
   # Database failures: critical - stop serving
   ```

4. **Monitor Health Trends:**
   ```bash
   # Response time increases: performance issues
   # Intermittent failures: network problems  
   # Consistent failures: configuration issues
   ```

### Integration with Main App

To add health checks to your main Flask/FastAPI app:

```python
# In main.py
from health_check import perform_health_check

@app.route('/health')
def health():
    return jsonify(perform_health_check())
```

This provides Railway with the `/health` endpoint for zero-downtime deployments and uptime monitoring.
