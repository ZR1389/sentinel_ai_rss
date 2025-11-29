"""
Trial reminder email system.

Sends automated emails at key trial milestones:
- Day 1: Welcome and onboarding
- Day 3: Feature highlight (monitoring alerts)
- Day 5: Last feature push (trip planner)
- Day 6: Conversion reminder

Run daily via cron to check and send due reminders.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, Any, List
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

try:
    from core.config import CONFIG
    DATABASE_URL = CONFIG.database.url
except Exception:
    DATABASE_URL = None

# Use centralized email dispatcher (Brevo first, SMTP fallback)
try:
    from email_dispatcher import send_email  # paid-plan gating inside
except Exception:
    def send_email(user_email: str, to_addr: str, subject: str, html_body: str, from_addr: str = None) -> bool:
        logger.warning(f"email_dispatcher not available, skipping email to {to_addr}")
        return False

# Email templates for trial stages
TRIAL_EMAIL_TEMPLATES = {
    'day_1': {
        'subject': 'Welcome to Your 7-Day Trial! 🚀',
        'html': """
        <h2>Welcome to Sentinel AI {plan}!</h2>
        <p>Hi {name},</p>
        <p>Your 7-day trial has started. Here's how to get the most from it:</p>
        <ul>
            <li><strong>Explore the Threat Map</strong>: View real-time global threats with {map_days} days of historical data</li>
            <li><strong>Chat with Sentinel AI</strong>: Ask about threats in any location ({chat_messages} messages available)</li>
            <li><strong>Set up Alerts</strong>: Get notified about threats in locations you care about</li>
        </ul>
        <p>Your trial ends on {trial_ends_date}. We'll remind you before it converts to paid.</p>
        <p>Questions? Reply to this email or visit our support portal.</p>
        <p>Happy exploring!<br>The Sentinel AI Team</p>
        """
    },
    'day_3': {
        'subject': 'Pro Tip: Set Up Location Monitoring 📍',
        'html': """
        <h2>Make the Most of Your Trial</h2>
        <p>Hi {name},</p>
        <p>You're 3 days into your trial! Here's a powerful feature many users love:</p>
        <h3>🔔 Saved Searches & Monitoring Alerts</h3>
        <p>Create up to {saved_searches} custom searches to monitor specific:</p>
        <ul>
            <li>Cities or regions you care about</li>
            <li>Threat types (terrorism, conflict, natural disasters)</li>
            <li>Severity levels (high-threat only)</li>
        </ul>
        <p>You'll get instant alerts when new threats match your criteria.</p>
        <p><a href="{app_url}/monitoring" style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Set Up Monitoring →</a></p>
        <p>Trial ends: {trial_ends_date}</p>
        <p>Best,<br>The Sentinel AI Team</p>
        """
    },
    'day_5': {
        'subject': '2 Days Left—Have You Tried Trip Planner? ✈️',
        'html': """
        <h2>Your Trial Ends in 2 Days</h2>
        <p>Hi {name},</p>
        <p>Just a heads-up: your trial converts to paid on {trial_ends_date}.</p>
        <h3>🗺️ Last Feature to Try: Trip Planner</h3>
        <p>Planning travel? Use our Trip Planner to:</p>
        <ul>
            <li>Assess risk for up to {trip_destinations} destinations</li>
            <li>Get route-specific threat analysis</li>
            <li>Download briefing packages for offline use</li>
        </ul>
        <p><a href="{app_url}/trip-planner" style="background: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Try Trip Planner →</a></p>
        <p>Not ready to commit? You can cancel anytime before {trial_ends_date} with no charge.</p>
        <p>Questions? We're here to help.</p>
        <p>Cheers,<br>The Sentinel AI Team</p>
        """
    },
    'day_6': {
        'subject': 'Tomorrow Your Trial Converts to Paid',
        'html': """
        <h2>Trial Ending Tomorrow</h2>
        <p>Hi {name},</p>
        <p>This is a final reminder that your {plan} trial ends tomorrow ({trial_ends_date}).</p>
        <h3>What Happens Next?</h3>
        <ul>
            <li><strong>If you have a payment method on file:</strong> Your subscription will automatically start at ${price}/month</li>
            <li><strong>If you want to cancel:</strong> <a href="{app_url}/settings/billing">Cancel your trial here</a> before {trial_ends_date}</li>
            <li><strong>If you downgrade:</strong> You'll return to the Free plan with limited features</li>
        </ul>
        <p>We hope Sentinel AI has been valuable for your security needs!</p>
        <p><a href="{app_url}/settings/billing" style="background: #dc3545; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Manage Subscription →</a></p>
        <p>Thank you,<br>The Sentinel AI Team</p>
        """
    }
}

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg2.connect(DATABASE_URL)

def _render_email(template: str, context: Dict[str, Any]) -> str:
    """Simple template rendering (replace {key} with values)."""
    html = TRIAL_EMAIL_TEMPLATES.get(template, {}).get('html', '')
    for key, value in context.items():
        html = html.replace(f'{{{key}}}', str(value))
    return html

def _get_plan_features(plan: str) -> Dict[str, Any]:
    """Get plan features for email context."""
    try:
        from config_data.plans import PLAN_FEATURES, PLAN_PRICING
        features = PLAN_FEATURES.get(plan.upper(), PLAN_FEATURES['FREE'])
        price = PLAN_PRICING.get(plan.upper(), 0)
        return {
            'chat_messages': features.get('chat_messages_monthly', 0),
            'map_days': features.get('map_access_days', 2),
            'saved_searches': features.get('saved_searches', 0),
            'trip_destinations': features.get('trip_planner_destinations', 0),
            'price': price
        }
    except Exception:
        return {
            'chat_messages': 500,
            'map_days': 30,
            'saved_searches': 3,
            'trip_destinations': 5,
            'price': 79
        }

def send_trial_reminder(user_id: int, user_email: str, plan: str, trial_day: int, trial_ends_at: datetime) -> bool:
    """
    Send trial reminder email for specific day milestone.
    
    Args:
        user_id: User ID
        user_email: User email address
        plan: Plan name (PRO, BUSINESS, etc.)
        trial_day: Day of trial (1, 3, 5, 6)
        trial_ends_at: When trial ends
    
    Returns:
        True if email sent successfully
    """
    template_key = f'day_{trial_day}'
    if template_key not in TRIAL_EMAIL_TEMPLATES:
        logger.warning(f"No email template for trial day {trial_day}")
        return False
    
    template = TRIAL_EMAIL_TEMPLATES[template_key]
    plan_features = _get_plan_features(plan)
    
    # Email context
    context = {
        'name': user_email.split('@')[0].capitalize(),  # Simple name extraction
        'plan': plan.upper(),
        'trial_ends_date': trial_ends_at.strftime('%B %d, %Y'),
        'app_url': os.getenv('FRONTEND_URL', 'https://sentinel-ai.app'),
        **plan_features
    }
    
    html_body = _render_email(template_key, context)
    subject = template['subject']
    
    try:
        # email_dispatcher enforces paid-plan; trial emails should go to all trials.
        # We pass user_email as both user and recipient; dispatcher will log if gated.
        success = send_email(user_email=user_email, to_addr=user_email, subject=subject, html_body=html_body)
        if success:
            logger.info(f"Sent trial day {trial_day} email to {user_email}")
            
            # Send push notification
            try:
                from webpush_send import broadcast_to_user
                push_messages = {
                    1: "Welcome! Your trial has started",
                    3: "Day 3: Set up location monitoring",
                    5: "2 days left - Try our Trip Planner",
                    6: "Your trial ends tomorrow"
                }
                broadcast_to_user(
                    user_email=user_email,
                    title=f"Trial Day {trial_day}",
                    body=push_messages.get(trial_day, f"Trial reminder - Day {trial_day}"),
                    url="/settings/billing"
                )
            except Exception as push_err:
                logger.warning(f"Push notification failed for {user_email}: {push_err}")
            
            # Log email sent (for tracking)
            try:
                with _conn() as conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO trial_emails_sent (user_id, email_type, sent_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (user_id, email_type) DO NOTHING
                        """,
                        (user_id, f'day_{trial_day}')
                    )
                    conn.commit()
            except Exception as e:
                logger.warning(f"Failed to log trial email: {e}")
        return success
    except Exception as e:
        logger.error(f"Failed to send trial reminder to {user_email}: {e}")
        return False

def check_and_send_trial_reminders() -> int:
    """
    Check all active trials and send reminder emails if due.
    Run this daily via cron.
    
    Returns:
        Number of reminder emails sent
    """
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not configured, skipping trial reminders")
        return 0
    
    sent_count = 0
    now = datetime.utcnow()
    
    try:
        with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get all active trials
            cur.execute(
                """
                SELECT id, email, plan, trial_started_at, trial_ends_at
                FROM users
                WHERE is_trial = TRUE
                  AND trial_started_at IS NOT NULL
                  AND trial_ends_at IS NOT NULL
                  AND trial_ends_at > NOW()
                """
            )
            active_trials = cur.fetchall() or []
        
        for user in active_trials:
            trial_started = user['trial_started_at']
            trial_ends = user['trial_ends_at']
            user_id = user['id']
            user_email = user['email']
            plan = user['plan']
            
            # Calculate trial day
            days_elapsed = (now - trial_started).days
            
            # Check which reminders to send
            reminders_to_send = []
            if days_elapsed == 1:
                reminders_to_send.append(1)
            elif days_elapsed == 3:
                reminders_to_send.append(3)
            elif days_elapsed == 5:
                reminders_to_send.append(5)
            elif days_elapsed == 6:
                reminders_to_send.append(6)
            
            # Check if already sent
            for day in reminders_to_send:
                try:
                    with _conn() as conn, conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT 1 FROM trial_emails_sent
                            WHERE user_id = %s AND email_type = %s
                            """,
                            (user_id, f'day_{day}')
                        )
                        already_sent = cur.fetchone() is not None
                    
                    if not already_sent:
                        if send_trial_reminder(user_id, user_email, plan, day, trial_ends):
                            sent_count += 1
                except Exception as e:
                    logger.error(f"Error checking/sending reminder for user {user_id}: {e}")
        
        logger.info(f"Trial reminder check complete: {sent_count} emails sent")
        return sent_count
    
    except Exception as e:
        logger.error(f"Failed to check trial reminders: {e}")
        return 0

def get_trial_status(user_id: int) -> Dict[str, Any]:
    """
    Get trial status and reminder history for a user.
    
    Returns:
        Dict with trial info and emails sent
    """
    if not DATABASE_URL:
        return {}
    
    try:
        with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT plan, is_trial, trial_started_at, trial_ends_at
                FROM users
                WHERE id = %s
                """,
                (user_id,)
            )
            user = cur.fetchone()
            if not user or not user['is_trial']:
                return {'is_trial': False}
            
            # Get sent emails
            cur.execute(
                """
                SELECT email_type, sent_at
                FROM trial_emails_sent
                WHERE user_id = %s
                ORDER BY sent_at
                """,
                (user_id,)
            )
            emails_sent = cur.fetchall() or []
            
            trial_started = user['trial_started_at']
            trial_ends = user['trial_ends_at']
            now = datetime.utcnow()
            
            return {
                'is_trial': True,
                'plan': user['plan'],
                'trial_started_at': trial_started.isoformat() if trial_started else None,
                'trial_ends_at': trial_ends.isoformat() if trial_ends else None,
                'days_remaining': (trial_ends - now).days if trial_ends else 0,
                'emails_sent': [
                    {
                        'type': e['email_type'],
                        'sent_at': e['sent_at'].isoformat() if e['sent_at'] else None
                    }
                    for e in emails_sent
                ]
            }
    except Exception as e:
        logger.error(f"Failed to get trial status for user {user_id}: {e}")
        return {}

__all__ = ['send_trial_reminder', 'check_and_send_trial_reminders', 'get_trial_status']
