# Deploying Context API

## Option 1: Deploy to Railway (Production PostgreSQL)

### Step 1: Push code to git
```bash
git add .
git commit -m "feat: add user context API for three products"
git push origin main
```

### Step 2: Apply migration on Railway
```bash
# Option A: Use Railway CLI
railway run psql $DATABASE_URL -f migrate_user_context.sql

# Option B: Use Railway shell
railway shell
psql $DATABASE_URL -f migrate_user_context.sql
exit

# Option C: Connect directly from local (if you have Railway DATABASE_URL)
# Get DATABASE_URL from Railway dashboard: Settings > Variables
export RAILWAY_DATABASE_URL="postgresql://..."
psql $RAILWAY_DATABASE_URL -f migrate_user_context.sql
```

### Step 3: Verify deployment
```bash
# Check Railway logs
railway logs

# Test API endpoint
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://sentinelairss-production.up.railway.app/api/context
```

---

## Option 2: Local Development (SQLite - Limited)

**Note:** SQLite doesn't support all PostgreSQL JSONB functions used in the context API. For full functionality, use PostgreSQL.

### Install PostgreSQL locally
```bash
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# macOS
brew install postgresql
brew services start postgresql

# Create database
createdb sentinel_dev
```

### Update .env.dev
```bash
# Replace SQLite with PostgreSQL
DATABASE_URL=postgresql://localhost/sentinel_dev
```

### Apply migration
```bash
psql sentinel_dev -f migrate_user_context.sql
```

---

## Testing the API

### 1. Get an access token
```bash
# Register or login
curl -X POST https://sentinelairss-production.up.railway.app/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"your@email.com","password":"yourpassword"}'

# Save the access token
export TOKEN="eyJhbGci..."
```

### 2. Test GET /api/context
```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://sentinelairss-production.up.railway.app/api/context
```

**Expected response (empty context):**
```json
{
  "ok": true,
  "investigation": null,
  "recent": [],
  "locations": []
}
```

### 3. Test POST /api/context (save investigation)
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "investigation",
    "data": {
      "topic": "Ransomware trends Q4 2025",
      "focus": "Healthcare sector",
      "started_at": "2025-11-21T10:00:00Z"
    }
  }' \
  https://sentinelairss-production.up.railway.app/api/context
```

**Expected response:**
```json
{
  "ok": true,
  "message": "Context updated"
}
```

### 4. Test POST /api/context (save query)
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "query",
    "data": {
      "query": "Ukraine cyber attacks",
      "timestamp": "2025-11-21T14:30:00Z",
      "product": "threat_map"
    }
  }' \
  https://sentinelairss-production.up.railway.app/api/context
```

### 5. Test POST /api/context (save location)
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "location",
    "data": {
      "name": "Kyiv, Ukraine",
      "lat": 50.4501,
      "lon": 30.5234,
      "saved_at": "2025-11-21T15:00:00Z",
      "product": "travel_risk_map"
    }
  }' \
  https://sentinelairss-production.up.railway.app/api/context
```

### 6. Test GET /api/context (verify saved data)
```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://sentinelairss-production.up.railway.app/api/context
```

**Expected response (with saved data):**
```json
{
  "ok": true,
  "investigation": {
    "topic": "Ransomware trends Q4 2025",
    "focus": "Healthcare sector",
    "started_at": "2025-11-21T10:00:00Z"
  },
  "recent": [
    {
      "query": "Ukraine cyber attacks",
      "timestamp": "2025-11-21T14:30:00Z",
      "product": "threat_map"
    }
  ],
  "locations": [
    {
      "name": "Kyiv, Ukraine",
      "lat": 50.4501,
      "lon": 30.5234,
      "saved_at": "2025-11-21T15:00:00Z",
      "product": "travel_risk_map"
    }
  ]
}
```

### 7. Test GET /api/context/search
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://sentinelairss-production.up.railway.app/api/context/search?q=ukraine"
```

**Expected response:**
```json
{
  "ok": true,
  "locations": [
    {
      "location": "Kyiv",
      "count": 156,
      "lat": 50.4501,
      "lon": 30.5234,
      "zoom": 12
    }
  ],
  "travel": {
    "label": "Kyiv",
    "lat": 50.4501,
    "lon": 30.5234
  }
}
```

### 8. Test POST /api/context (clear investigation)
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "clear",
    "data": {}
  }' \
  https://sentinelairss-production.up.railway.app/api/context
```

---

## Troubleshooting

### Error: "Database unavailable"
**Cause:** `fetch_one`, `fetch_all`, or `execute` not loaded from `db_utils.py`

**Fix:** Restart Flask app to reload imports

### Error: "relation user_context does not exist"
**Cause:** Migration not applied to database

**Fix:** Run migration SQL file on the correct database

### Error: "User not found"
**Cause:** JWT token is valid but user doesn't exist in users table

**Fix:** Verify user exists: `SELECT * FROM users WHERE email='your@email.com'`

### Error: 401 Unauthorized
**Cause:** Invalid or expired JWT token

**Fix:** Login again to get a fresh token

---

## Database Verification

### Check if table exists
```sql
SELECT * FROM user_context LIMIT 1;
```

### Check user context data
```sql
SELECT 
    u.email,
    uc.active_investigation,
    uc.recent_queries,
    uc.saved_locations,
    uc.updated_at
FROM user_context uc
JOIN users u ON u.id = uc.user_id;
```

### Check trigger is working
```sql
-- Update a row
UPDATE user_context SET active_investigation = '{"test": true}'::jsonb WHERE user_id = 1;

-- Verify updated_at changed
SELECT user_id, updated_at FROM user_context WHERE user_id = 1;
```

---

## Next Steps

1. **Deploy to Railway** - Push code and apply migration
2. **Test all endpoints** - Use curl commands above
3. **Frontend integration** - Create React hooks for context API
4. **Monitor usage** - Check Railway logs for errors

**Railway Deployment:**
```bash
git add .
git commit -m "feat: add user context API"
git push origin main
# Railway auto-deploys
# Wait 1-2 minutes, then apply migration via Railway CLI
```
