# Trial System - Quick Setup Card

## ✅ Completed
- [x] Database migration applied
- [x] Brevo email integration (tested ✅)
- [x] Cron jobs added to railway_cron.py
- [x] API endpoints ready

## 🔧 Setup Required (5 minutes)

### 1. Add CRON_SECRET to Railway
```bash
# Generate secret
openssl rand -hex 32

# Add to Railway Dashboard > Variables
CRON_SECRET=<your-generated-secret>
```

### 2. Set Up External Cron (Choose One)

**Option A: EasyCron.com (Recommended)**
1. Sign up at easycron.com (free tier available)
2. Add two cron jobs:

**Job 1: Trial Reminders**
- URL: `https://gondola.proxy.rlwy.net:37509/api/cron/trial-reminders`
- Method: POST
- Headers: `X-Cron-Secret: <your-secret>`
- Schedule: Every day at 10:00 AM UTC

**Job 2: Trial Expiration**
- URL: `https://gondola.proxy.rlwy.net:37509/api/cron/check-trials`
- Method: POST
- Headers: `X-Cron-Secret: <your-secret>`
- Schedule: Every day at 2:00 AM UTC

**Option B: Cron-job.org**
Same setup as EasyCron, different UI.

**Option C: Your Own Server**
```bash
# Add to crontab
0 10 * * * curl -X POST -H "X-Cron-Secret: YOUR_SECRET" https://gondola.proxy.rlwy.net:37509/api/cron/trial-reminders
0 2 * * * curl -X POST -H "X-Cron-Secret: YOUR_SECRET" https://gondola.proxy.rlwy.net:37509/api/cron/check-trials
```

### 3. Test the System
```bash
# Test trial start (use a FREE user token)
curl -X POST https://gondola.proxy.rlwy.net:37509/api/user/trial/start \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"plan": "PRO"}'

# Check your email (info@zikarisk.com) for Day 1 welcome email

# Manually trigger reminder check
curl -X POST https://gondola.proxy.rlwy.net:37509/api/cron/trial-reminders \
  -H "X-Cron-Secret: <YOUR_SECRET>"
```

---

## 📧 Email Configuration (Already Set)
- ✅ Brevo API Key: Configured
- ✅ Sender Email: info@zikarisk.com
- ✅ Sender Name: Zika Risk
- ✅ Test Email: Sent successfully

**Note:** Newsletter list (ID=3) is separate from trial emails. Trial emails use transactional API.

---

## 📋 Trial Email Schedule
| Day | Email | Purpose |
|-----|-------|---------|
| 1 | Welcome | Onboarding & feature overview |
| 3 | Monitoring | Highlight saved searches feature |
| 5 | Trip Planner | Last feature push, 2 days warning |
| 6 | Conversion | 24h reminder, cancellation option |

---

## 🧪 Quick Test Checklist
- [ ] Set CRON_SECRET in Railway
- [ ] Set up external cron (EasyCron/cron-job.org)
- [ ] Create test FREE user
- [ ] Start trial for test user
- [ ] Check email inbox for Day 1 welcome
- [ ] Manually trigger `trial_reminders` cron
- [ ] Verify in database: `SELECT * FROM trial_emails_sent;`

---

## 🔗 Important URLs
- **Backend:** https://gondola.proxy.rlwy.net:37509
- **Frontend:** https://zikarisk.com
- **Trial Start:** POST /api/user/trial/start
- **Trial Status:** GET /api/user/trial/status
- **Cron Reminders:** POST /api/cron/trial-reminders
- **Cron Expiration:** POST /api/cron/check-trials

---

## 📚 Full Documentation
- `PRODUCTION_DEPLOYMENT_COMPLETE.md` - Complete setup guide
- `TRIAL_API_FRONTEND.md` - Frontend integration
- `CRON_JOBS_CONFIG.md` - Cron setup details
- `TRIAL_EMAIL_CUSTOMIZATION.md` - Edit email templates

---

## 🆘 Quick Troubleshooting

**Emails not sending?**
```bash
python -c "from utils.brevo_sender import send_trial_email_brevo; send_trial_email_brevo('test@example.com', 'Test', '<p>Test</p>')"
```

**Check active trials:**
```sql
SELECT email, plan, trial_ends_at FROM users WHERE is_trial=TRUE;
```

**Check sent emails:**
```sql
SELECT u.email, te.email_type, te.sent_at 
FROM trial_emails_sent te 
JOIN users u ON u.id=te.user_id 
ORDER BY te.sent_at DESC LIMIT 10;
```

---

## ✨ That's It!

Once you:
1. Add CRON_SECRET to Railway (1 min)
2. Set up external cron (3 min)
3. Test trial flow (1 min)

**You're live! 🚀**

Expected Results:
- 30-40% of FREE users start trials
- 20-30% of trials convert to paid
- Automated emails reduce support load

Questions? Check the full docs above.
