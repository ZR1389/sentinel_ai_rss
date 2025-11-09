#!/bin/bash
# Setup cron job for raw_alerts cleanup

SCRIPT_DIR="/Users/zikarakita/Documents/sentinel_ai_rss"
PYTHON_PATH="/opt/homebrew/bin/python3"
LOG_FILE="/Users/zikarakita/Documents/sentinel_ai_rss/logs/cleanup.log"

# Create logs directory if it doesn't exist
mkdir -p "${SCRIPT_DIR}/logs"

# Create the cron job entry
CRON_JOB="0 2 1 */3 * cd ${SCRIPT_DIR} && ${PYTHON_PATH} cleanup_raw_alerts.py --days 90 >> ${LOG_FILE} 2>&1"

# Add to crontab
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo "✅ Cron job added successfully!"
echo "Schedule: Every 3 months on the 1st at 2:00 AM"
echo "Command: $CRON_JOB"
echo ""
echo "To view: crontab -l"
echo "To remove: crontab -e (then delete the line)"
echo "Logs will be written to: $LOG_FILE"
