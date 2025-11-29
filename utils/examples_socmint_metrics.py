#!/usr/bin/env python3
"""
Quick Start: SOCMINT Metrics & Logging
Example usage patterns for the enhanced SOCMINT subsystem
"""

# 1. Basic Metrics Access
# ======================
from socmint_service import get_cache_metrics

metrics = get_cache_metrics()
print(f"Cache Hit Rate: {metrics['hit_rate_percent']}%")
print(f"Apify Calls Saved: {metrics['hits']}")

# 2. Performance Logging
# ======================
from socmint_service import log_cache_performance_summary

# Call this periodically (hourly/daily in production)
log_cache_performance_summary()

# 3. Cache Operations (automatic tracking)
# ========================================
from socmint_service import SocmintService

service = SocmintService()

# Cache miss → fresh scrape (tracked automatically)
result = service.get_cached_socmint_data('instagram', 'threat_actor', ttl_minutes=120)
if not result['success']:
    result = service.run_instagram_scraper('threat_actor', results_limit=10)
    service.save_socmint_data('instagram', 'threat_actor', result['data'])

# 4. Alert Enrichment (cache-aware)
# ==================================
from ioc_extractor import extract_social_media_iocs, enrich_alert_with_socmint

alert = {
    'uuid': 'alert-123',
    'title': 'Threat actor @malware_king posts IOCs',
    'summary': 'New indicators shared on instagram',
}

# Extract IOCs
iocs = extract_social_media_iocs(f"{alert['title']} {alert['summary']}")
print(f"Found {len(iocs)} social media IOCs")

# Enrich with SOCMINT (uses cache automatically)
enriched_alert = enrich_alert_with_socmint(alert, iocs)
print(f"Added {len(enriched_alert.get('enrichments', {}).get('osint', []))} OSINT entries")

# 5. API Endpoints (Flask app)
# ============================
"""
GET /api/socmint/metrics
→ Returns cache performance statistics

POST /api/socmint/metrics/reset
→ Resets all counters to zero

Example Response:
{
  "status": "success",
  "metrics": {
    "hits": 105,
    "misses": 45,
    "total_requests": 150,
    "apify_calls": 45,
    "cache_saves": 45,
    "errors": 0,
    "hit_rate_percent": 70.0
  }
}
"""

# 6. Periodic Maintenance
# =======================
from socmint_service import reset_cache_metrics
import schedule  # pip install schedule

def daily_metrics_report():
    """Daily routine: log summary then reset."""
    log_cache_performance_summary()
    reset_cache_metrics()

# Schedule for daily 00:00 UTC
# schedule.every().day.at("00:00").do(daily_metrics_report)

# 7. Monitoring Alerts
# ====================
def check_cache_health():
    """Alert if cache performance degrades."""
    metrics = get_cache_metrics()
    
    if metrics['total_requests'] > 100:  # Minimum sample size
        if metrics['hit_rate_percent'] < 40:
            print("⚠️  WARNING: Low cache hit rate (<40%)")
        
        if metrics['errors'] > metrics['total_requests'] * 0.05:
            print("⚠️  WARNING: High error rate (>5%)")
        
        if metrics['hit_rate_percent'] > 70:
            print("✅ Cache performing well (>70% hit rate)")

check_cache_health()

# 8. Custom TTL for Different Use Cases
# =====================================
service = SocmintService()

# Short TTL for active threat actors (15 min)
fresh_data = service.get_cached_socmint_data('instagram', 'apt_group', ttl_minutes=15)

# Long TTL for stable profiles (24 hours)
stable_data = service.get_cached_socmint_data('facebook', 'news.page', ttl_minutes=1440)

print("\n✅ All examples complete! Check SOCMINT_METRICS.md for full documentation.")
