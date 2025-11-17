"""geocoding_monitor.py

Monitor geocoding backlog and notify when cleared.
Sends notifications via configured channels when backlog drops below threshold.
"""

import os
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger("geocoding_monitor")

# Thresholds
BACKLOG_CLEARED_THRESHOLD = 500  # Consider cleared when < 500 alerts missing coords
COVERAGE_TARGET = 90.0  # Target 90%+ coverage

# Track last notification to avoid spam
_last_notification_time: Optional[datetime] = None
_notification_cooldown = timedelta(hours=6)


def get_geocoding_status(conn) -> Dict:
    """Get current geocoding coverage statistics"""
    cur = conn.cursor()
    
    # Total alerts and coverage
    cur.execute("""
        SELECT 
            COUNT(*) AS total_alerts,
            COUNT(latitude) AS with_coords,
            ROUND(100.0 * COUNT(latitude) / NULLIF(COUNT(*), 0), 1) AS pct_covered
        FROM alerts
    """)
    row = cur.fetchone()
    total_alerts = row[0]
    with_coords = row[1]
    pct_covered = float(row[2]) if row[2] else 0.0
    
    # Remaining backlog (has location text but no coords)
    cur.execute("""
        SELECT COUNT(*) AS missing_coords
        FROM alerts
        WHERE (latitude IS NULL OR longitude IS NULL)
          AND (city IS NOT NULL AND city != '' OR country IS NOT NULL AND country != '')
    """)
    backlog = cur.fetchone()[0]
    
    # Geocoding cache stats
    cur.execute("SELECT COUNT(*) FROM geocoded_locations")
    cache_size = cur.fetchone()[0]
    
    cur.close()
    
    return {
        'total_alerts': total_alerts,
        'with_coords': with_coords,
        'pct_covered': pct_covered,
        'backlog': backlog,
        'cache_size': cache_size,
        'is_cleared': backlog < BACKLOG_CLEARED_THRESHOLD,
        'target_reached': pct_covered >= COVERAGE_TARGET
    }


def should_notify() -> bool:
    """Check if enough time has passed since last notification"""
    global _last_notification_time
    
    if _last_notification_time is None:
        return True
    
    return datetime.utcnow() - _last_notification_time > _notification_cooldown


def send_notification(status: Dict):
    """Send notification about backlog clearance via available channels"""
    global _last_notification_time
    
    message = f"""
🎯 Geocoding Backlog Cleared!

Coverage: {status['pct_covered']}% ({status['with_coords']:,}/{status['total_alerts']:,})
Backlog: {status['backlog']:,} alerts remaining
Cache: {status['cache_size']:,} locations

{"✅ Target reached!" if status['target_reached'] else "⚠️ Below target (90%)"}

Next step: Disable aggressive cron in railway.toml
    """
    
    sent_via = []
    
    # Try Telegram
    try:
        import requests
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if bot_token and chat_id:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }, timeout=10)
            
            if resp.status_code == 200:
                sent_via.append("Telegram")
                logger.info("[geocoding_monitor] Notification sent via Telegram")
    except Exception as e:
        logger.warning(f"[geocoding_monitor] Telegram notification failed: {e}")
    
    # Try email (Brevo)
    try:
        import sib_api_v3_sdk
        from sib_api_v3_sdk.rest import ApiException
        
        api_key = os.getenv("BREVO_API_KEY")
        sender_email = os.getenv("BREVO_SENDER_EMAIL", "noreply@zikarisk.com")
        admin_email = os.getenv("ADMIN_EMAIL", "info@zikarisk.com")
        
        if api_key and admin_email:
            configuration = sib_api_v3_sdk.Configuration()
            configuration.api_key['api-key'] = api_key
            api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
            
            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": admin_email}],
                sender={"email": sender_email, "name": "Sentinel AI Monitor"},
                subject="🎯 Geocoding Backlog Cleared",
                html_content=message.replace('\n', '<br>')
            )
            
            api_instance.send_transac_email(send_smtp_email)
            sent_via.append("Email")
            logger.info("[geocoding_monitor] Notification sent via Email")
    except Exception as e:
        logger.warning(f"[geocoding_monitor] Email notification failed: {e}")
    
    if sent_via:
        _last_notification_time = datetime.utcnow()
        logger.info(f"[geocoding_monitor] Notification sent via: {', '.join(sent_via)}")
    else:
        logger.warning("[geocoding_monitor] No notification channels available")
    
    return sent_via


def check_and_notify():
    """Check geocoding status and send notification if backlog is cleared"""
    try:
        from db_utils import _get_db_connection
        
        with _get_db_connection() as conn:
            status = get_geocoding_status(conn)
            
            logger.info(
                f"[geocoding_monitor] Coverage: {status['pct_covered']}%, "
                f"Backlog: {status['backlog']:,}, "
                f"Cache: {status['cache_size']:,}"
            )
            
            # Notify if cleared and cooldown period passed
            if status['is_cleared'] and should_notify():
                channels = send_notification(status)
                return {
                    'notified': True,
                    'channels': channels,
                    'status': status
                }
            
            return {
                'notified': False,
                'status': status,
                'reason': 'cooldown' if not should_notify() else 'not_cleared'
            }
            
    except Exception as e:
        logger.error(f"[geocoding_monitor] Check failed: {e}")
        return {'error': str(e)}
