# Geocode Cache Database Fix

## Issue
RSS processor was failing with database error:
```
[DB_ERROR] EXECUTE failed - Query: INSERT INTO geocode_cache (city, country, lat, lon, updated_at)
VALUES (%s, %s, %s, %s, NOW()) ON CONFLICT (city,...
Error: there is no unique or exclusion constraint matching the ON CONFLICT specification
```

## Root Cause
The `geocode_cache` table was missing a **UNIQUE constraint** on `(city, country)` columns. The `ON CONFLICT` clause in the upsert operation requires this constraint to function.

## Solution Applied
Created migration `migrate_geocode_cache_constraint.sql` that adds:
```sql
ALTER TABLE geocode_cache
ADD CONSTRAINT geocode_cache_city_country_key 
UNIQUE (city, country);
```

## Local Testing ✅
```
✓ Insert succeeded
✓ Lookup succeeded: (40.7128, -74.006)
✓ Update (ON CONFLICT) succeeded
✓ Updated lookup succeeded: (41.0, -75.0)
```

## Railway Deployment

### Option 1: Automatic Migration (Recommended)
Railway should auto-apply this migration on next deploy. The constraint creation is idempotent (safe to run multiple times).

### Option 2: Manual Migration (If Needed)
If errors persist in Railway logs, manually run:

```bash
# Connect to Railway database
railway connect postgres

# Run migration
\i migrate_geocode_cache_constraint.sql

# Verify constraint exists
\d geocode_cache

# Should show:
# "geocode_cache_city_country_key" UNIQUE CONSTRAINT, btree (city, country)
```

### Option 3: One-liner
```bash
railway run psql $DATABASE_URL -c "ALTER TABLE geocode_cache ADD CONSTRAINT geocode_cache_city_country_key UNIQUE (city, country);"
```

## Verification
Check Railway logs after deployment:
```bash
railway logs
```

Should see:
- ✅ No more `[DB_ERROR] EXECUTE failed` for geocode_cache
- ✅ `[DB_SUCCESS] EXECUTE completed` for geocode cache operations
- ✅ RSS processor successfully caching coordinates

## Impact
- **Before**: Geocode cache insertions failing, no coordinate caching
- **After**: Geocode cache working, coordinates cached properly, faster location lookups

## Files Changed
- `migrate_geocode_cache_constraint.sql` (new)
- Commit: `8aa3e87`

## Related Code
- `rss_processor.py::_geo_db_store()` - Uses ON CONFLICT for upserts
- `city_utils.py::cache_geocode_result()` - Uses ON CONFLICT for upserts
