# Trial Strategy Implementation Guide

Complete 7-day trial system for PRO and BUSINESS plans with automated reminder emails and conversion optimization.

## 📋 Overview

**Trial Duration:**
- PRO: 7 days (requires credit card)
- BUSINESS: 7 days (requires credit card)
- ENTERPRISE: 14 days (no credit card required)

**Automated Email Schedule:**
- Day 1: Welcome & onboarding
- Day 3: Feature highlight (monitoring alerts)
- Day 5: Last feature push (trip planner)
- Day 6: Conversion reminder (24h warning)

---

## 🏗️ Architecture

### Components

1. **`utils/trial_manager.py`** - Core trial logic
   - `start_trial(user, plan)` - Start trial
   - `end_trial(user, convert_to_paid)` - End/convert trial
   - `check_expired_trials()` - Daily cron to expire trials

2. **`utils/trial_reminder.py`** - Email automation (NEW)
   - `send_trial_reminder(user_id, email, plan, day, ends_at)` - Send specific day email
   - `check_and_send_trial_reminders()` - Daily cron to check and send
   - `get_trial_status(user_id)` - Get trial info + email history

3. **`migrations/003_trial_email_tracking.sql`** - Database table (NEW)
   - Tracks which emails have been sent to prevent duplicates

### API Endpoints

**Trial Management:**
- `POST /api/user/trial/start` - Start trial (sends Day 1 email)
- `POST /api/user/trial/end` - End trial (user cancellation)
- `GET /api/user/trial/status` - Get trial status + email history

**Cron Jobs:**
- `POST /api/cron/check-trials` - Expire trials and convert/downgrade
- `POST /api/cron/trial-reminders` - Send reminder emails (NEW)

---

## 🚀 Setup Instructions

### 1. Run Database Migration

```bash
psql $DATABASE_URL -f migrations/003_trial_email_tracking.sql
```

### 2. Configure Environment Variables

```bash
# Email configuration (required for trial reminders)
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASS=<your-sendgrid-api-key>
EMAIL_FROM=trials@sentinel-ai.app
FRONTEND_URL=https://sentinel-ai.app

# Cron secret for secure cron endpoints
CRON_SECRET=<generate-random-secret>
```

### 3. Set Up Cron Jobs

**Railway Configuration:**

Add to `railway.toml`:

```toml
[[crons]]
name = "check_expired_trials"
schedule = "0 2 * * *"  # Daily at 2 AM UTC
command = "curl -X POST -H 'X-Cron-Secret: $CRON_SECRET' $RAILWAY_STATIC_URL/api/cron/check-trials"

[[crons]]
name = "trial_reminders"
schedule = "0 10 * * *"  # Daily at 10 AM UTC
command = "curl -X POST -H 'X-Cron-Secret: $CRON_SECRET' $RAILWAY_STATIC_URL/api/cron/trial-reminders"
```

**Manual Testing:**

```bash
# Test trial expiration check
curl -X POST \
  -H "X-Cron-Secret: $CRON_SECRET" \
  https://your-backend.railway.app/api/cron/check-trials

# Test reminder emails
curl -X POST \
  -H "X-Cron-Secret: $CRON_SECRET" \
  https://your-backend.railway.app/api/cron/trial-reminders
```

---

## 📧 Email Templates

All email templates are in `utils/trial_reminder.py`. Customize these messages:

### Day 1: Welcome & Onboarding
**Goal:** Set expectations and guide first steps
- Subject: "Welcome to Your 7-Day Trial! 🚀"
- Content: Feature overview, getting started tips, trial end date

### Day 3: Feature Highlight
**Goal:** Drive engagement with monitoring alerts
- Subject: "Pro Tip: Set Up Location Monitoring 📍"
- Content: Benefits of saved searches, how to create alerts, CTA to monitoring page

### Day 5: Final Feature Push
**Goal:** Showcase high-value feature (trip planner)
- Subject: "2 Days Left—Have You Tried Trip Planner? ✈️"
- Content: Trip planner benefits, reminder of trial end, cancellation option

### Day 6: Conversion Warning
**Goal:** Inform about upcoming charge, reduce friction
- Subject: "Tomorrow Your Trial Converts to Paid"
- Content: What happens next, pricing, cancel link, billing page CTA

---

## 🎯 Frontend Integration

### Pricing Page Implementation

**Trial CTA Button:**

```jsx
// On PRO/BUSINESS plan cards
<button onClick={handleStartTrial}>
  Start 7-Day Free Trial
</button>

// On click:
async function handleStartTrial(plan) {
  const response = await fetch('/api/user/trial/start', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ plan })
  });
  
  const data = await response.json();
  
  if (data.ok) {
    // Show success message
    alert(`${plan} trial started! Ends ${data.trial_ends_at}`);
    // Redirect to onboarding or dashboard
    router.push('/dashboard');
  } else {
    // Show error (e.g., already on trial, not on FREE plan)
    alert(data.error);
  }
}
```

**Trial Status Banner:**

```jsx
// Show on dashboard/map/chat pages during trial
function TrialBanner({ trialStatus }) {
  if (!trialStatus.is_trial) return null;
  
  return (
    <div className="trial-banner">
      <strong>{trialStatus.plan} Trial Active</strong>
      <span>{trialStatus.days_remaining} days remaining</span>
      <Link href="/settings/billing">Manage Trial</Link>
    </div>
  );
}

// Fetch trial status
useEffect(() => {
  fetch('/api/user/trial/status', {
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => setTrialStatus(data));
}, []);
```

**Cancellation Flow:**

```jsx
// In /settings/billing page
async function handleCancelTrial() {
  const confirmed = confirm(
    'Cancel your trial? You\'ll return to the Free plan.'
  );
  
  if (!confirmed) return;
  
  const response = await fetch('/api/user/trial/end', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ convert_to_paid: false })
  });
  
  const data = await response.json();
  
  if (data.ok) {
    alert('Trial cancelled. You\'re now on the Free plan.');
    router.push('/dashboard');
  }
}
```

---

## 🧪 Testing Strategy

### Manual Testing Flow

1. **Start Trial:**
   ```bash
   curl -X POST \
     -H "Authorization: Bearer $FREE_USER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"plan": "PRO"}' \
     https://your-backend.railway.app/api/user/trial/start
   ```

2. **Check Status:**
   ```bash
   curl -X GET \
     -H "Authorization: Bearer $USER_TOKEN" \
     https://your-backend.railway.app/api/user/trial/status
   ```

3. **Manually Trigger Reminder (Day 1):**
   ```bash
   # After trial start, run reminder cron
   curl -X POST \
     -H "X-Cron-Secret: $CRON_SECRET" \
     https://your-backend.railway.app/api/cron/trial-reminders
   
   # Check email inbox for Day 1 welcome email
   ```

4. **Test Expiration:**
   ```bash
   # Manually set trial_ends_at to past date in DB
   psql $DATABASE_URL -c "UPDATE users SET trial_ends_at = NOW() - INTERVAL '1 day' WHERE email='test@example.com';"
   
   # Run expiration cron
   curl -X POST \
     -H "X-Cron-Secret: $CRON_SECRET" \
     https://your-backend.railway.app/api/cron/check-trials
   
   # Verify user downgraded or converted
   ```

### Email Preview Testing

To preview emails without SMTP:

1. Update `utils/trial_reminder.py`:
   ```python
   # In send_trial_reminder(), add:
   print(f"=== EMAIL PREVIEW: {subject} ===")
   print(html_body)
   print("=== END EMAIL ===")
   ```

2. Run reminder cron and check logs

---

## 📊 Monitoring & Analytics

### Key Metrics to Track

1. **Trial Starts:**
   ```sql
   SELECT COUNT(*) FROM plan_changes 
   WHERE reason = 'trial_start' 
   AND created_at > NOW() - INTERVAL '30 days';
   ```

2. **Trial Conversion Rate:**
   ```sql
   SELECT 
     COUNT(CASE WHEN reason='trial_converted' THEN 1 END)::float / 
     COUNT(CASE WHEN reason='trial_start' THEN 1 END) * 100 AS conversion_rate
   FROM plan_changes
   WHERE created_at > NOW() - INTERVAL '30 days';
   ```

3. **Email Open/Click Rates:**
   - Integrate with SendGrid/Mailgun webhooks
   - Track opens/clicks in `trial_emails_sent` table

4. **Cancellation Reasons:**
   - Add optional `cancellation_reason` field to `plan_changes`
   - Survey users on trial cancellation

---

## 🔧 Troubleshooting

### Emails Not Sending

1. **Check SMTP credentials:**
   ```bash
   echo $SMTP_HOST $SMTP_USER $SMTP_PASS
   ```

2. **Test SMTP connection:**
   ```python
   import smtplib
   with smtplib.SMTP('smtp.sendgrid.net', 587) as s:
       s.starttls()
       s.login('apikey', 'YOUR_KEY')
       print("SMTP OK")
   ```

3. **Check email_dispatcher.py:**
   - Ensure paid plan check is bypassed for trial emails
   - Look for `EMAIL_PUSH_ENABLED` flag

### Duplicate Emails

- Check `trial_emails_sent` table for duplicates
- Ensure cron runs once daily (not multiple times)
- Verify `UNIQUE(user_id, email_type)` constraint exists

### Trials Not Expiring

1. **Check cron is running:**
   ```bash
   railway logs --filter="check-trials"
   ```

2. **Manually trigger:**
   ```bash
   curl -X POST -H "X-Cron-Secret: $CRON_SECRET" $BACKEND_URL/api/cron/check-trials
   ```

3. **Verify trial dates:**
   ```sql
   SELECT email, trial_ends_at, is_trial FROM users WHERE is_trial = TRUE;
   ```

---

## 📈 Optimization Tips

### Email Engagement

1. **Personalization:**
   - Use user's actual name (from profile or parse email)
   - Show their actual usage stats in emails

2. **A/B Testing:**
   - Test different subject lines
   - Vary CTA button text/color
   - Test email send times (morning vs evening)

3. **Segmentation:**
   - Different emails for engaged vs inactive users
   - Highlight features based on user behavior

### Conversion Optimization

1. **Reduce Friction:**
   - Pre-fill payment form with trial user info
   - Offer annual discount on conversion
   - Show social proof (# of active users)

2. **Extend Trial Selectively:**
   - Offer +3 days if user is highly engaged
   - Auto-extend if user added payment but not yet active

3. **Exit Survey:**
   - Ask why they're cancelling
   - Offer plan downgrade (PRO → FREE) instead of full cancel

---

## ✅ Launch Checklist

- [ ] Database migration applied (`003_trial_email_tracking.sql`)
- [ ] SMTP credentials configured and tested
- [ ] Cron jobs scheduled in Railway
- [ ] Trial CTA added to pricing page
- [ ] Trial banner added to dashboard
- [ ] Cancellation flow implemented in settings
- [ ] Email templates reviewed and customized
- [ ] Test trial flow end-to-end (start → emails → expire)
- [ ] Monitoring/analytics dashboards set up
- [ ] Support team briefed on trial system

---

## 🎉 Success!

Your trial strategy is now fully implemented and ready to drive conversions!

**Expected Impact:**
- 30-40% trial signup rate (from FREE users)
- 20-30% trial-to-paid conversion rate
- Reduced support burden (automated onboarding emails)
- Increased feature engagement during trial period

Monitor metrics weekly and iterate on email content/timing for best results.
