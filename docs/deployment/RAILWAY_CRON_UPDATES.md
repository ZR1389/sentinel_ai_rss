# Railway Cron Jobs - Path Updates Required

## ⚠️ IMPORTANT: Update All Cron Job Commands in Railway Dashboard

After workspace reorganization, all cron job commands need path updates.

## How to Update
1. Go to Railway Dashboard → Your Project → Settings → Cron
2. Edit each cron job's "Custom Start Command"
3. Update paths as shown below
4. Save each change

---

## 📋 Cron Job Command Updates

### 1. Location Quality Monitor (NEW)
**Old:** `python cron_location_quality.py`
**New:** `python workers/cron_location_quality.py`
- Schedule: `09***` (daily at 09:00)

### 2. Retention Cleanup
**Old:** `python railway_cron.py cleanup`
**New:** `python workers/railway_cron.py cleanup`
- Schedule: `0 */6 * * *` (every 6 hours)

### 3. Daily Vacuum
**Old:** `python railway_cron.py vacuum`
**New:** `python workers/railway_cron.py vacuum`
- Schedule: `0 2 * * *` (daily at 2am)

### 4. RSS Ingest
**Old:** `python railway_cron.py rss`
**New:** `python workers/railway_cron.py rss`
- Schedule: `0 6,18 * * *` (6am and 6pm)

### 5. Engine Enrich
**Old:** `python railway_cron.py engine`
**New:** `python workers/railway_cron.py engine`
- Schedule: `0 7,19 * * *` (7am and 7pm)

### 6. Proximity Check
**Old:** `python railway_cron.py proximity`
**New:** `python workers/railway_cron.py proximity`
- Schedule: `0 8,20 * * *` (8am and 8pm)

### 7. Geocode Backfill
**Old:** `python railway_cron.py geocode`
**New:** `python workers/railway_cron.py geocode`
- Schedule: `30 3 * * *` (daily at 3:30am)

### 8. Daily Notify
**Old:** `python railway_cron.py notify`
**New:** `python workers/railway_cron.py notify`
- Schedule: `0 8 * * *` (daily at 8am)

### 9. Trial Reminders
**Old:** `python railway_cron.py trial_reminders`
**New:** `python workers/railway_cron.py trial_reminders`
- Schedule: `0 10 * * *` (daily at 10am)

### 10. Check Expired Trials
**Old:** `python railway_cron.py check_trials`
**New:** `python workers/railway_cron.py check_trials`
- Schedule: `0 2 * * *` (daily at 2am)

---

## ✅ Verification Checklist

After updating all cron jobs:
- [ ] All 10 cron jobs updated with new paths
- [ ] Location quality monitor (NEW) added with `workers/` path
- [ ] Test deploy to verify no path errors in logs
- [ ] Monitor first cron run for each job
- [ ] Check Railway logs for any "ModuleNotFoundError" or "FileNotFoundError"

---

## 🔍 How to Test

After deployment, manually trigger a cron job in Railway Dashboard:
1. Go to Settings → Cron
2. Click "Run Now" on any job
3. Check logs for successful execution
4. Look for: "✅ [job_name] completed successfully"

---

## 🚨 Troubleshooting

If you see errors like:
```
python: can't open file 'railway_cron.py': [Errno 2] No such file or directory
```

**Solution:** The cron job command wasn't updated. Go back to Railway Dashboard and add `workers/` prefix.

---

## 📝 Notes

- All worker scripts are now in `workers/` directory
- Main app is in `core/main.py` (Procfile already updated)
- No changes needed to environment variables
- No changes needed to cron schedules (timing stays the same)
