"""
Weekly Digest Scheduler - APScheduler Background Job
Runs daily to check for schedules that need execution
"""

import os
import logging
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.db_utils import fetch_all, execute
from utils.weekly_digest_generator import generate_weekly_digest_pdf, send_digest_email

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler = None


def process_weekly_digests():
    """
    Process all weekly digest schedules that are due for execution.
    Called daily at 6am UTC by APScheduler.
    """
    try:
        logger.info("Starting weekly digest processing...")
        
        # Get all active schedules that need to run (next_run is in the past or now)
        schedules = fetch_all("""
            SELECT id, user_id, email, timezone, hour, day_of_week, filters, next_run
            FROM weekly_digest_schedules
            WHERE active = true
            AND next_run <= NOW()
            AND failure_count < 5
            ORDER BY next_run ASC
        """)
        
        if not schedules:
            logger.info("No weekly digests due for processing")
            return
        
        logger.info(f"Processing {len(schedules)} weekly digest schedule(s)...")
        success_count = 0
        failure_count = 0
        
        for schedule in schedules:
            schedule_id = schedule['id'] if isinstance(schedule, dict) else schedule[0]
            user_id = schedule['user_id'] if isinstance(schedule, dict) else schedule[1]
            email = schedule['email'] if isinstance(schedule, dict) else schedule[2]
            filters = schedule['filters'] if isinstance(schedule, dict) else schedule[6]
            
            try:
                # Calculate date range (last 7 days)
                now_utc = datetime.now(pytz.UTC)
                week_end = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                week_start = week_end - timedelta(days=7)
                
                logger.info(f"Generating weekly digest: schedule_id={schedule_id}, email={email}")
                
                # Generate PDF
                file_path, file_id = generate_weekly_digest_pdf(
                    user_id=user_id,
                    email=email,
                    filters=filters,
                    week_start=week_start,
                    week_end=week_end
                )
                
                if not file_path:
                    logger.warning(f"No alerts found for weekly digest: schedule_id={schedule_id}, email={email}")
                    # Update schedule but don't increment failure count (no alerts is not a failure)
                    update_schedule_next_run(schedule)
                    continue
                
                # Send email
                email_sent = send_digest_email(
                    email=email,
                    file_path=file_path,
                    week_start=week_start,
                    week_end=week_end
                )
                
                if email_sent:
                    # Update schedule: reset failure count, update last_run and next_run
                    execute("""
                        UPDATE weekly_digest_schedules
                        SET last_run = NOW(),
                            next_run = %s,
                            failure_count = 0
                        WHERE id = %s
                    """, (calculate_next_run(schedule), schedule_id))
                    
                    success_count += 1
                    logger.info(f"Weekly digest sent successfully: schedule_id={schedule_id}, email={email}")
                else:
                    # Increment failure count
                    execute("""
                        UPDATE weekly_digest_schedules
                        SET failure_count = failure_count + 1,
                            next_run = %s
                        WHERE id = %s
                    """, (calculate_next_run(schedule), schedule_id))
                    
                    failure_count += 1
                    logger.error(f"Failed to send weekly digest email: schedule_id={schedule_id}, email={email}")
                
            except Exception as e:
                logger.error(f"Error processing weekly digest: schedule_id={schedule_id}, email={email}, error={e}")
                import traceback
                traceback.print_exc()
                
                # Increment failure count
                execute("""
                    UPDATE weekly_digest_schedules
                    SET failure_count = failure_count + 1,
                        next_run = %s
                    WHERE id = %s
                """, (calculate_next_run(schedule), schedule_id))
                
                failure_count += 1
        
        logger.info(f"Weekly digest processing complete: success={success_count}, failures={failure_count}")
        
    except Exception as e:
        logger.error(f"Weekly digest processing error: {e}")
        import traceback
        traceback.print_exc()


def calculate_next_run(schedule) -> datetime:
    """Calculate the next run time for a schedule."""
    try:
        if isinstance(schedule, dict):
            timezone_str = schedule['timezone']
            hour = schedule['hour']
            day_of_week = schedule['day_of_week']
        else:
            timezone_str = schedule[3]
            hour = schedule[4]
            day_of_week = schedule[5]
        
        # Get current time in user's timezone
        tz = pytz.timezone(timezone_str)
        now_utc = datetime.now(pytz.UTC)
        now_local = now_utc.astimezone(tz)
        
        # Calculate next occurrence
        days_ahead = day_of_week - now_local.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        
        next_run_local = now_local.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
        next_run_utc = next_run_local.astimezone(pytz.UTC).replace(tzinfo=None)
        
        return next_run_utc
        
    except Exception as e:
        logger.error(f"Error calculating next run: {e}")
        # Default to 7 days from now
        return datetime.now(pytz.UTC).replace(tzinfo=None) + timedelta(days=7)


def update_schedule_next_run(schedule):
    """Update schedule's next_run without modifying failure count."""
    try:
        schedule_id = schedule['id'] if isinstance(schedule, dict) else schedule[0]
        next_run = calculate_next_run(schedule)
        execute("""
            UPDATE weekly_digest_schedules
            SET next_run = %s
            WHERE id = %s
        """, (next_run, schedule_id))
    except Exception as e:
        logger.error(f"Error updating schedule next_run: {e}")


def start_weekly_digest_scheduler():
    """Start the APScheduler background job for weekly digests."""
    global _scheduler
    
    # Check if already running
    if _scheduler is not None and _scheduler.running:
        logger.info("Weekly digest scheduler already running")
        return
    
    # Check if enabled via env var
    if os.getenv('WEEKLY_DIGEST_ENABLED', 'true').lower() != 'true':
        logger.info("Weekly digest scheduler disabled (WEEKLY_DIGEST_ENABLED=false)")
        return
    
    try:
        logger.info("Starting weekly digest scheduler...")
        
        _scheduler = BackgroundScheduler(daemon=True)
        
        # Run daily at 6am UTC
        trigger = CronTrigger(hour=6, minute=0, timezone=pytz.UTC)
        _scheduler.add_job(
            process_weekly_digests,
            trigger=trigger,
            id='weekly_digest_processor',
            name='Weekly Digest Processor',
            replace_existing=True,
            max_instances=1
        )
        
        _scheduler.start()
        logger.info("✓ Weekly digest scheduler started (runs daily at 6am UTC)")
        
    except Exception as e:
        logger.error(f"Failed to start weekly digest scheduler: {e}")
        import traceback
        traceback.print_exc()


def stop_weekly_digest_scheduler():
    """Stop the weekly digest scheduler."""
    global _scheduler
    
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Weekly digest scheduler stopped")
        _scheduler = None
