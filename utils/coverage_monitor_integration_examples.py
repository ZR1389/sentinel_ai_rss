#!/usr/bin/env python3
"""
Quick Integration Example - Coverage Monitor Wiring

Shows how to integrate the coverage monitor into existing code.
Copy these patterns into your production code.
"""

# ========================================
# Example 1: Recording Alerts (in rss_processor.py or threat_engine.py)
# ========================================

def process_alert_example(alert_data):
    """Example: Record alert after processing"""
    # ... existing alert processing code ...
    
    # NEW: Record for coverage monitoring
    try:
        from coverage_monitor import get_coverage_monitor
        
        monitor = get_coverage_monitor()
        monitor.record_alert(
            country=alert_data.get("country"),
            city=alert_data.get("city"),
            region=alert_data.get("region"),
            confidence=float(alert_data.get("confidence", 0.5)),
            source_count=len(alert_data.get("sources", [])),
        )
    except Exception as e:
        # Don't break alert processing if monitoring fails
        import logging
        logging.getLogger(__name__).debug(f"Coverage monitor recording failed: {e}")
    
    # ... rest of alert processing ...


# ========================================
# Example 2: Recording Location Extraction (in chat_handler.py)
# ========================================

def handle_user_query_with_monitoring(message, email, **kwargs):
    """Example: Record location extraction attempts"""
    # ... existing query handling ...
    
    # Extract location
    from services.location_extractor import extract_location_from_query
    
    result = extract_location_from_query(message)
    city = result.get('city')
    country = result.get('country')
    method = result.get('method')
    
    # NEW: Record extraction attempt
    try:
        from coverage_monitor import get_coverage_monitor
        
        monitor = get_coverage_monitor()
        success = bool(city or country)
        monitor.record_location_extraction(success=success, method=method)
    except Exception:
        pass  # Silent fail on monitoring
    
    # ... continue with query handling ...


# ========================================
# Example 3: Recording Advisory Attempts (in advisor.py or chat_handler.py)
# ========================================

def generate_advisory_with_monitoring(alert, user_message, profile):
    """Example: Record advisory generation attempts"""
    from api.advisor import render_advisory
    
    # Generate advisory
    advisory = render_advisory(alert, user_message, profile)
    
    # NEW: Record attempt
    try:
        from coverage_monitor import get_coverage_monitor
        
        monitor = get_coverage_monitor()
        
        # Check if advisory was gated
        if "NO INTELLIGENCE AVAILABLE" in advisory:
            # Determine gate reason
            if "location mismatch" in advisory.lower() or "mismatch" in advisory.lower():
                reason = "location mismatch"
            elif "low confidence" in advisory.lower() or "confidence" in advisory.lower():
                reason = "low confidence"
            elif "insufficient" in advisory.lower() or "data volume" in advisory.lower():
                reason = "insufficient data"
            else:
                reason = "unknown"
            
            monitor.record_advisory_attempt(generated=False, gate_reason=reason)
        else:
            monitor.record_advisory_attempt(generated=True)
    except Exception:
        pass  # Silent fail on monitoring
    
    return advisory


# ========================================
# Example 4: Flask Monitoring Endpoints (in main.py)
# ========================================

"""
Add these routes to your Flask app:
"""

# @app.route("/api/monitoring/coverage", methods=["GET"])
# @login_required
# def get_coverage_report():
#     \"\"\"Get comprehensive coverage monitoring report\"\"\"
#     try:
#         from coverage_monitor import get_coverage_monitor
#         
#         monitor = get_coverage_monitor()
#         report = monitor.get_comprehensive_report()
#         
#         return jsonify(report), 200
#     except Exception as e:
#         logger.error(f"Coverage monitoring failed: {e}")
#         return jsonify({"error": "Monitoring unavailable"}), 500
# 
# 
# @app.route("/api/monitoring/gaps", methods=["GET"])
# @login_required
# def get_coverage_gaps_endpoint():
#     \"\"\"Get geographic coverage gaps\"\"\"
#     try:
#         from coverage_monitor import get_coverage_monitor
#         from flask import request
#         
#         monitor = get_coverage_monitor()
#         
#         # Parse query parameters
#         min_alerts = int(request.args.get("min_alerts_7d", 5))
#         max_age = int(request.args.get("max_age_hours", 24))
#         
#         gaps = monitor.get_coverage_gaps(
#             min_alerts_7d=min_alerts,
#             max_age_hours=max_age,
#         )
#         
#         return jsonify({
#             "gaps": gaps,
#             "count": len(gaps),
#             "parameters": {
#                 "min_alerts_7d": min_alerts,
#                 "max_age_hours": max_age,
#             }
#         }), 200
#     except Exception as e:
#         logger.error(f"Coverage gaps query failed: {e}")
#         return jsonify({"error": "Query failed"}), 500
# 
# 
# @app.route("/api/monitoring/stats", methods=["GET"])
# @login_required
# def get_monitoring_stats():
#     \"\"\"Get location extraction and advisory gating stats\"\"\"
#     try:
#         from coverage_monitor import get_coverage_monitor
#         
#         monitor = get_coverage_monitor()
#         
#         return jsonify({
#             "location_extraction": monitor.get_location_extraction_stats(),
#             "advisory_gating": monitor.get_advisory_gating_stats(),
#         }), 200
#     except Exception as e:
#         logger.error(f"Stats query failed: {e}")
#         return jsonify({"error": "Query failed"}), 500


# ========================================
# Example 5: Periodic Log Summary (in main.py)
# ========================================

"""
Add this to your application startup:
"""

# def setup_periodic_monitoring():
#     \"\"\"Setup periodic coverage monitoring summary logs\"\"\"
#     from apscheduler.schedulers.background import BackgroundScheduler
#     from coverage_monitor import get_coverage_monitor
#     import logging
#     
#     logger = logging.getLogger(__name__)
#     monitor = get_coverage_monitor()
#     
#     def log_coverage_summary():
#         try:
#             monitor.log_summary()
#         except Exception as e:
#             logger.error(f"Coverage summary logging failed: {e}")
#     
#     scheduler = BackgroundScheduler()
#     
#     # Log summary every 6 hours
#     scheduler.add_job(
#         log_coverage_summary,
#         'interval',
#         hours=6,
#         id='coverage_summary',
#     )
#     
#     scheduler.start()
#     logger.info("[App] Periodic coverage monitoring initialized (every 6h)")
#     
#     return scheduler
# 
# 
# # In your app initialization:
# # scheduler = setup_periodic_monitoring()


# ========================================
# Example 6: Manual Coverage Check (for debugging)
# ========================================

def debug_coverage_status():
    """Manual check of current coverage status"""
    from coverage_monitor import get_coverage_monitor
    
    monitor = get_coverage_monitor()
    
    print("\n" + "="*60)
    print("COVERAGE STATUS")
    print("="*60)
    
    # Get gaps
    gaps = monitor.get_coverage_gaps(min_alerts_7d=5, max_age_hours=24)
    print(f"\nCoverage Gaps: {len(gaps)}")
    for gap in gaps[:10]:
        print(f"  - {gap['country']} ({gap['region']}): {gap['issues']}")
    
    # Get stats
    loc_stats = monitor.get_location_extraction_stats()
    print(f"\nLocation Extraction Success Rate: {loc_stats['success_rate']}%")
    
    gate_stats = monitor.get_advisory_gating_stats()
    print(f"Advisory Generation Success Rate: {gate_stats['success_rate']}%")
    print(f"Advisory Gating Rate: {gate_stats['gating_rate']}%")
    
    print("="*60 + "\n")


# ========================================
# Example 7: Export Metrics (for external monitoring tools)
# ========================================

def export_metrics_to_file():
    """Export coverage metrics to JSON file"""
    from coverage_monitor import get_coverage_monitor
    import json
    from datetime import datetime
    
    monitor = get_coverage_monitor()
    
    # Export to JSON
    metrics_json = monitor.export_to_json()
    
    # Save to file with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"coverage_metrics_{timestamp}.json"
    
    with open(filename, 'w') as f:
        f.write(metrics_json)
    
    print(f"Metrics exported to {filename}")


# ========================================
# Integration Summary
# ========================================

"""
Minimal Integration Steps:

1. Record alerts in RSS processor or threat engine:
   monitor.record_alert(country, city, region, confidence, source_count)

2. Record location extractions in chat handler:
   monitor.record_location_extraction(success, method)

3. Record advisory attempts in advisor or chat handler:
   monitor.record_advisory_attempt(generated, gate_reason)

4. Optional: Add Flask monitoring endpoints
5. Optional: Setup periodic log summaries
6. Optional: Export metrics to external tools

That's it! The coverage monitor is thread-safe and handles all failures gracefully.
"""

if __name__ == "__main__":
    print(__doc__)
    print("\nRun debug_coverage_status() to see current coverage state")
    print("Or wire the integration examples into your production code")
