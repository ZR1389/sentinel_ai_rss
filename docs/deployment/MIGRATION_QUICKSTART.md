# Quick Start: Apply Itinerary Migration

## Method 1: Railway Shell (Recommended)

1. Open Railway dashboard
2. Navigate to your `sentinel_ai_rss` service
3. Click **Shell** tab
4. Run:
```bash
python apply_itinerary_migration.py
```

Expected output:
```
Applying migration 004_travel_risk_itineraries.sql...
✓ Table 'travel_itineraries' created successfully
✓ Created 4 indexes: [...]
✓ View 'active_itineraries' created successfully
✓ Trigger 'trigger_itinerary_updated_at' created successfully

✅ Migration applied successfully!
```

## Method 2: Railway Connect (psql)

```bash
railway connect
```

Then in psql:
```sql
\i migrations/004_travel_risk_itineraries.sql
\dt travel_itineraries
\d travel_itineraries
```

## Method 3: One-time Run Command

From your local terminal:
```bash
railway run --service sentinel_ai_rss python apply_itinerary_migration.py
```

## Verify Migration

Check if table exists:
```bash
railway run --service sentinel_ai_rss python -c "
from db_utils import fetch_one
result = fetch_one('SELECT COUNT(*) FROM travel_itineraries')
print(f'✓ Table exists, row count: {result}')
"
```

## Test API Endpoint

After migration, test with curl:
```bash
# Get your JWT token from browser console or login
export TOKEN="your_jwt_token_here"

# Test stats endpoint (should return {total: 0, active: 0, deleted: 0})
curl https://sentinel-ai-rss-production.up.railway.app/api/travel-risk/itinerary/stats \
  -H "Authorization: Bearer $TOKEN"
```

Expected response:
```json
{
  "ok": true,
  "total": 0,
  "active": 0,
  "deleted": 0
}
```

## Troubleshooting

### Error: "relation 'travel_itineraries' already exists"
✅ Safe to ignore - migration already applied

### Error: "could not translate host name"
❌ Run from Railway shell, not locally

### Error: "permission denied"
❌ Check DATABASE_URL has proper permissions

## Next Steps

Once migration is applied:
1. ✅ Test endpoints in production
2. ✅ Update frontend to use new endpoints
3. ✅ Monitor Railway logs for errors
4. ✅ Start creating itineraries from Travel Risk Map UI
