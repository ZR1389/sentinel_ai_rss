#!/usr/bin/env python3
"""
cron_location_quality.py

Daily location quality monitoring job.
Run via Railway cron or manually to check data quality.

Usage:
    python workers/cron_location_quality.py [--notify-threshold 5]
"""

import os
import sys
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Run daily location quality check"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Location quality monitoring')
    parser.add_argument('--days', type=int, default=7, help='Days to analyze (default: 7)')
    parser.add_argument('--notify-threshold', type=int, default=5, 
                       help='Send notification if high-severity anomalies exceed this count (default: 5)')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Run without sending notifications')
    args = parser.parse_args()
    
    try:
        from monitoring.location_quality_monitor import get_location_quality_report
        
        logger.info(f"=== Location Quality Check ({args.days} days) ===")
        
        # Generate report
        report = get_location_quality_report(args.days)
        
        # Summary
        logger.info(f"Total Alerts: {report['total_alerts']}")
        logger.info(f"Quality Score: {report['quality_score']}% (TIER1 methods)")
        
        # Method breakdown
        logger.info("\nLocation Methods:")
        for method_stat in report['by_method']:
            logger.info(f"  {method_stat['method']:20s} {method_stat['count']:5d} ({method_stat['percentage']:5.1f}%)")
        
        # Anomalies
        anomalies = report.get('anomalies', [])
        high_severity_count = sum(1 for a in anomalies if a.get('severity') == 'high')
        medium_severity_count = sum(1 for a in anomalies if a.get('severity') == 'medium')
        
        logger.info(f"\nAnomalies Found: {len(anomalies)} total")
        logger.info(f"  High severity: {high_severity_count}")
        logger.info(f"  Medium severity: {medium_severity_count}")
        
        if anomalies:
            logger.info("\nTop Anomalies:")
            for anomaly in anomalies[:10]:  # Show first 10
                logger.info(f"  [{anomaly['severity'].upper()}] {anomaly['type']}: {anomaly['details']}")
        
        # Send notification if threshold exceeded
        if high_severity_count >= args.notify_threshold:
            logger.warning(f"⚠️  High-severity anomalies ({high_severity_count}) exceed threshold ({args.notify_threshold})")
            
            if not args.dry_run:
                send_notification(report, high_severity_count)
            else:
                logger.info("(dry-run mode - notification not sent)")
        else:
            logger.info(f"✅ Quality check passed (high-severity anomalies: {high_severity_count})")
        
        # Return appropriate exit code
        sys.exit(0 if high_severity_count < args.notify_threshold else 1)
        
    except Exception as e:
        logger.error(f"Location quality check failed: {e}", exc_info=True)
        sys.exit(2)


def send_notification(report: dict, high_severity_count: int):
    """Send notification about location quality issues"""
    try:
        # Try to send email notification
        from email_dispatcher import send_email
        
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@example.com')
        
        subject = f"⚠️ Location Quality Alert: {high_severity_count} High-Severity Anomalies"
        
        body = f"""
Location Quality Monitoring Report
===================================

Period: Last {report['period_days']} days
Total Alerts: {report['total_alerts']}
Quality Score: {report['quality_score']}%

High-Severity Anomalies: {high_severity_count}

Top Issues:
"""
        
        for anomaly in report.get('anomalies', [])[:5]:
            if anomaly.get('severity') == 'high':
                body += f"\n- {anomaly['type']}: {anomaly['details']}"
        
        body += f"\n\nView full report: {os.getenv('APP_URL', 'http://localhost:5000')}/admin/location/quality"
        body += f"\nView validations: {os.getenv('APP_URL', 'http://localhost:5000')}/admin/location/validations?corrections=true"
        
        send_email(
            to_email=admin_email,
            subject=subject,
            body=body
        )
        
        logger.info(f"Notification sent to {admin_email}")
        
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        
        # Fallback: log to Slack/webhook if configured
        try_webhook_notification(report, high_severity_count)


def try_webhook_notification(report: dict, count: int):
    """Fallback notification via webhook (e.g., Slack)"""
    webhook_url = os.getenv('ALERT_WEBHOOK_URL')
    
    if not webhook_url:
        logger.info("No webhook configured (ALERT_WEBHOOK_URL)")
        return
    
    try:
        import requests
        
        message = {
            "text": f"⚠️ Location Quality Alert: {count} high-severity anomalies detected",
            "attachments": [
                {
                    "color": "warning",
                    "fields": [
                        {"title": "Period", "value": f"Last {report['period_days']} days", "short": True},
                        {"title": "Total Alerts", "value": str(report['total_alerts']), "short": True},
                        {"title": "Quality Score", "value": f"{report['quality_score']}%", "short": True},
                        {"title": "Anomalies", "value": str(count), "short": True}
                    ]
                }
            ]
        }
        
        response = requests.post(webhook_url, json=message, timeout=10)
        response.raise_for_status()
        
        logger.info("Webhook notification sent successfully")
        
    except Exception as e:
        logger.error(f"Webhook notification failed: {e}")


if __name__ == "__main__":
    main()
