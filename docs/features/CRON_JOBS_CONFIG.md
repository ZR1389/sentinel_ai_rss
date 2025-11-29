# Railway Cron Jobs Configuration
# Run using: python railway_cron.py <operation>

## Core Maintenance Jobs

### Daily Cleanup (2 AM UTC)
```bash
python railway_cron.py cleanup
```
- Cleans up old alerts beyond retention period
- Runs daily at 2:00 AM UTC

### Weekly Vacuum (Sunday 3 AM UTC)
```bash
python railway_cron.py vacuum
```
- Performs database VACUUM operation
- Runs weekly on Sunday at 3:00 AM UTC

---

## Ingestion Jobs

### RSS Ingestion (Every 15 minutes)
```bash
python railway_cron.py rss
```
- Fetches and processes RSS feeds
- Runs every 15 minutes

### Threat Engine Enrichment (Every 5 minutes)
```bash
python railway_cron.py engine
```
- Enriches new alerts with LLM analysis
- Runs every 5 minutes

### GDELT Enrichment (Every 30 minutes)
```bash
python railway_cron.py gdelt_enrich
```
- Enriches GDELT events
- Runs every 30 minutes

### ACLED Data Collection (Daily 4 AM UTC)
```bash
python railway_cron.py acled
```
- Collects ACLED conflict data
- Runs daily at 4:00 AM UTC

---

## User Notification Jobs

### Alert Notifications (Every 10 minutes)
```bash
python railway_cron.py notify
```
- Sends pending alerts via email/Telegram
- Runs every 10 minutes

### Proximity Checks (Every hour)
```bash
python railway_cron.py proximity
```
- Checks for proximity-based alerts
- Runs hourly

---

## Trial Management Jobs (NEW)

### Trial Reminder Emails (Daily 10 AM UTC)
```bash
python railway_cron.py trial_reminders
```
- Sends Day 1, 3, 5, 6 trial reminder emails
- Runs daily at 10:00 AM UTC
- Checks which emails are due and sends them

### Trial Expiration Check (Daily 2 AM UTC)
```bash
python railway_cron.py check_trials
```
- Checks for expired trials
- Converts to paid (if payment method) or downgrades to FREE
- Sends confirmation emails
- Runs daily at 2:00 AM UTC

---

## Cron Schedule Summary

| Job | Frequency | Time (UTC) | Command |
|-----|-----------|-----------|---------|
| Cleanup | Daily | 2:00 AM | `python railway_cron.py cleanup` |
| Vacuum | Weekly (Sun) | 3:00 AM | `python railway_cron.py vacuum` |
| RSS Ingest | Every 15 min | - | `python railway_cron.py rss` |
| Threat Engine | Every 5 min | - | `python railway_cron.py engine` |
| GDELT Enrich | Every 30 min | - | `python railway_cron.py gdelt_enrich` |
| ACLED Collect | Daily | 4:00 AM | `python railway_cron.py acled` |
| Notifications | Every 10 min | - | `python railway_cron.py notify` |
| Proximity | Hourly | - | `python railway_cron.py proximity` |
| **Trial Reminders** | **Daily** | **10:00 AM** | `python railway_cron.py trial_reminders` |
| **Check Trials** | **Daily** | **2:00 AM** | `python railway_cron.py check_trials` |

---

## Setup Instructions

### 1. Local Testing
```bash
# Activate virtual environment
source venv/bin/activate

# Set environment variables
export DATABASE_URL="postgresql://..."
export BREVO_API_KEY="xkeysib-..."
export BREVO_SENDER_EMAIL="info@zikarisk.com"

# Test trial reminder
python railway_cron.py trial_reminders

# Test trial expiration
python railway_cron.py check_trials
```

### 2. Railway Deployment

**Option A: Railway Cron (if available)**
Add to Railway dashboard:
- Schedule: `0 10 * * *` (10 AM daily)
- Command: `python railway_cron.py trial_reminders`

- Schedule: `0 2 * * *` (2 AM daily)
- Command: `python railway_cron.py check_trials`

**Option B: External Cron (EasyCron, Cron-job.org, etc.)**
Create HTTP endpoint triggers and call via curl:
```bash
# In railway_cron.py, you can also use main.py cron endpoints:
curl -X POST \
  -H "X-Cron-Secret: $CRON_SECRET" \
  https://your-backend.railway.app/api/cron/trial-reminders

curl -X POST \
  -H "X-Cron-Secret: $CRON_SECRET" \
  https://your-backend.railway.app/api/cron/check-trials
```

**Option C: Railway Deployment with Scheduler Service**
Use a separate scheduler service (APScheduler, Celery Beat, etc.) running on Railway.

---

## Environment Variables Required

For trial emails to work, ensure these are set in Railway:

```bash
# Brevo Email
BREVO_API_KEY=<your-brevo-api-key>
BREVO_SENDER_EMAIL=info@zikarisk.com
BREVO_SENDER_NAME=Zika Risk

# Frontend URL (for email links)
FRONTEND_URL=https://zikarisk.com

# Cron secret (for HTTP endpoint security)
CRON_SECRET=<generate-random-secret>

# Database
DATABASE_URL=postgresql://...
```

---

## Monitoring

### Check Cron Logs
```bash
# Railway CLI
railway logs --filter="railway_cron"

# Check specific job
railway logs --filter="trial_reminders"
```

### Verify Trial Emails Sent
```sql
-- Check recent trial emails
SELECT 
  u.email,
  te.email_type,
  te.sent_at,
  u.trial_ends_at
FROM trial_emails_sent te
JOIN users u ON u.id = te.user_id
WHERE te.sent_at > NOW() - INTERVAL '7 days'
ORDER BY te.sent_at DESC;

-- Check active trials
SELECT 
  email,
  plan,
  trial_started_at,
  trial_ends_at,
  DATE_PART('day', trial_ends_at - NOW()) as days_remaining
FROM users
WHERE is_trial = TRUE
ORDER BY trial_ends_at;
```

---

## Troubleshooting

### Trial emails not sending
1. Check Brevo API key: `echo $BREVO_API_KEY`
2. Test Brevo connection:
   ```python
   from utils.brevo_sender import send_trial_email_brevo
   send_trial_email_brevo('test@example.com', 'Test', '<p>Test</p>')
   ```
3. Check logs for errors: `railway logs --filter="trial_reminder"`

### Trials not expiring
1. Check cron is running: `python railway_cron.py check_trials`
2. Verify database: `SELECT * FROM users WHERE is_trial=TRUE AND trial_ends_at < NOW();`
3. Check logs: `railway logs --filter="check_trials"`

---

## Manual Operations

### Send test trial email
```python
from utils.trial_reminder import send_trial_reminder
from datetime import datetime, timedelta

send_trial_reminder(
    user_id=1,
    user_email='test@example.com',
    plan='PRO',
    trial_day=1,
    trial_ends_at=datetime.utcnow() + timedelta(days=7)
)
```

### Manually expire a trial
```python
from utils.trial_manager import end_trial

user = {'id': 1, 'email': 'test@example.com', 'plan': 'PRO', 'is_trial': True}
result = end_trial(user, convert_to_paid=False)
print(result)
```

---

**All trial cron jobs are now configured and ready!**
