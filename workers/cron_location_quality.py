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
import signal
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Timeout handler to prevent infinite execution
class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Job execution exceeded timeout limit")

def main():
    """Run daily location quality check"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Location quality monitoring')
    parser.add_argument('--days', type=int, default=7, help='Days to analyze (default: 7)')
    parser.add_argument('--notify-threshold', type=int, default=5, 
                       help='Send notification if high-severity anomalies exceed this count (default: 5)')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Run without sending notifications')
    parser.add_argument('--timeout', type=int, default=300,
                       help='Maximum execution time in seconds (default: 300 = 5 minutes)')
    args = parser.parse_args()
    
    # Set timeout alarm
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(args.timeout)
    
    try:
        # Add parent directory to path for imports
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        from monitoring.location_quality_monitor import get_location_quality_report
        
        logger.info(f"=== Location Quality Check ({args.days} days) ===")
        logger.info(f"Timeout set to {args.timeout} seconds")
        
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
        
        # Cancel alarm before exiting
        signal.alarm(0)
        
        # Return appropriate exit code
        sys.exit(0 if high_severity_count < args.notify_threshold else 1)
    
    except TimeoutError as e:
        logger.error(f"❌ TIMEOUT: {e}")
        logger.error(f"Job exceeded {args.timeout} seconds - forcing exit")
        signal.alarm(0)  # Cancel alarm
        sys.exit(124)  # Standard timeout exit code
        
    except Exception as e:
        logger.error(f"Location quality check failed: {e}", exc_info=True)
        signal.alarm(0)  # Cancel alarm
        sys.exit(2)


def send_notification(report: dict, high_severity_count: int):
    """Send notification about location quality issues"""
    try:
        # Try to send email notification
        from utils.email_dispatcher import send_email
        
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
        
        # Correct function signature: send_email(user_email, to_addr, subject, html_body, from_addr)
        # For admin notifications, use admin_email as both user_email (for plan check) and to_addr
        try:
            send_email(
                user_email=admin_email,  # Required: user email for plan check
                to_addr=admin_email,      # Required: recipient email
                subject=subject,          # Required: email subject
                html_body=body,           # Required: email body (accepts plain text too)
                from_addr=None            # Optional: from address (uses default)
            )
            logger.info(f"Email notification sent to {admin_email}")
        except Exception as email_err:
            logger.error(f"Email send failed: {email_err}")
            raise  # Re-raise to trigger fallback
        
    except Exception as e:
        logger.error(f"Failed to send email notification: {e}")
        
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
