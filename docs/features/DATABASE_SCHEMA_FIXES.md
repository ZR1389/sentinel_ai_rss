# Database Schema Issues & Fixes

## Issues Found

Yes, there **WERE** errors in the database tables and code. Here's what was wrong:

### ❌ Problem 1: Missing Columns in `alerts` Table

**Issue:** The `alerts` table was missing critical columns that the code references:
- `source_kind` - Only existed in `raw_alerts`, not in `alerts`
- `source_tag` - Only existed in `raw_alerts`, not in `alerts`  
- `threat_score_components` - JSONB field for SOCMINT breakdown (may not exist in older databases)

**Impact:** Frontend couldn't directly filter by ACLED vs RSS alerts without checking UUID prefixes.

**Status:** ✅ FIXED

### ❌ Problem 2: Wrong Data Types in `alerts` Table

**Issue:** Critical numeric fields were stored as TEXT instead of NUMERIC:
```sql
-- WRONG (from schema dump)
score text,                      -- Should be: numeric
confidence text,                 -- Should be: numeric  
future_risk_probability text,    -- Should be: numeric
```

**Impact:** 
- Can't do numeric comparisons directly in SQL
- Can't use numeric indexes efficiently
- Risk of storing invalid non-numeric values
- Query performance degradation

**Status:** ✅ FIXED with migration

### ❌ Problem 3: Internal vs Database Field Name Mismatch

**Issue:** Code uses `threat_score` internally but database column is named `score`:

```python
# threat_scorer.py returns:
{"score": 75.5, ...}  # ✅ Correct

# threat_engine.py calculates:
alert['threat_score'] = final_score  # ❌ Wrong - not a database column

# db_utils.py expects:
a.get("score")  # ✅ Correct
```

**Impact:** If `threat_score` is set but `score` isn't, database gets wrong/missing values.

**Status:** ✅ FIXED - now sets both `threat_score` (internal) and `score` (database)

## Fixes Applied

### 1. Migration SQL Script

Created: `migrations/003_add_source_metadata_and_fix_types.sql`

**What it does:**
- ✅ Adds `source_kind` column to `alerts` table
- ✅ Adds `source_tag` column to `alerts` table  
- ✅ Adds `threat_score_components` JSONB column to `alerts` table
- ✅ Converts `score` from TEXT to NUMERIC with 0-100 constraint
- ✅ Converts `confidence` from TEXT to NUMERIC with 0-1 constraint
- ✅ Converts `future_risk_probability` from TEXT to NUMERIC with 0-1 constraint
- ✅ Creates performance indexes for filtering and queries
- ✅ Backfills existing alerts with proper `source_kind` values

**Run this migration:**
```bash
psql $DATABASE_URL -f migrations/003_add_source_metadata_and_fix_types.sql
```

### 2. threat_engine.py Updates

**Changes:**
```python
# BEFORE: source_kind/source_tag were lost during enrichment
alert = enrich_single_alert(raw_alert)  # Lost source metadata

# AFTER: Preserve source metadata from raw_alerts
if 'source_kind' not in alert or not alert.get('source_kind'):
    # Infer from UUID if not present
    alert['source_kind'] = 'intelligence' if alert.get('uuid', '').startswith('acled:') else 'rss'
if 'source_tag' not in alert:
    alert['source_tag'] = alert.get('source_tag', '')

# BEFORE: Only set threat_score (not a database column)
alert['threat_score'] = final_score  

# AFTER: Set both internal and database fields
final_score = _clamp_score(base_score + socmint_weighted)
alert['threat_score'] = final_score  # Internal use
alert['score'] = final_score          # Database field
```

### 3. db_utils.py Updates

**Changes:**
```python
# BEFORE: Missing columns in save_alerts_to_db()
columns = [
    "uuid", "title", ..., "embedding"
]

# AFTER: Added source metadata and threat_score_components
columns = [
    "uuid", "title", ..., 
    "source_kind", "source_tag", "threat_score_components",
    "embedding"
]

# BEFORE: Missing in row coercion
return (
    ...,
    pgvector_embedding,
)

# AFTER: Added new fields with fallback logic
return (
    ...,
    a.get("source_kind") or ('intelligence' if str(aid).startswith('acled:') else 'rss'),
    a.get("source_tag") or '',
    _json(a.get("threat_score_components")),
    pgvector_embedding,
)
```

### 4. main.py API Updates

**Changes:**
```python
# BEFORE: Missing source_kind, source_tag in SELECT
SELECT uuid, title, ..., threat_score_components FROM alerts

# AFTER: Include all metadata fields
SELECT 
    uuid, title, ..., 
    threat_score_components,
    source_kind, source_tag,
    latitude, longitude
FROM alerts
```

## Verification Steps

### 1. Run the Migration
```bash
# Check current types
psql $DATABASE_URL -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'alerts' AND column_name IN ('score', 'confidence', 'source_kind', 'source_tag', 'threat_score_components');"

# Run migration
psql $DATABASE_URL -f migrations/003_add_source_metadata_and_fix_types.sql

# Verify after
psql $DATABASE_URL -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'alerts' AND column_name IN ('score', 'confidence', 'source_kind', 'source_tag', 'threat_score_components');"
```

Expected output:
```
column_name              | data_type
-------------------------+----------
score                    | numeric
confidence               | numeric  
source_kind              | text
source_tag               | text
threat_score_components  | jsonb
```

### 2. Test ACLED Collection
```bash
# Run ACLED collector
python acled_collector.py

# Check raw_alerts
psql $DATABASE_URL -c "SELECT uuid, source_kind, source_tag FROM raw_alerts WHERE uuid LIKE 'acled:%' LIMIT 3;"

# Run threat engine to enrich
curl -X POST "http://localhost:8080/engine/run" -H "Content-Type: application/json" -d '{"limit": 10}'

# Check enriched alerts have source metadata
psql $DATABASE_URL -c "SELECT uuid, source, source_kind, source_tag, score, confidence FROM alerts WHERE uuid LIKE 'acled:%' LIMIT 3;"
```

### 3. Test Frontend API
```bash
# Get alerts with source filtering
curl "http://localhost:8080/alerts/latest?limit=10" \
  -H "Authorization: Bearer YOUR_TOKEN" | jq '.items[] | {uuid, source_kind, score, threat_score_components}'
```

Expected response:
```json
{
  "uuid": "acled:123456",
  "source_kind": "intelligence",
  "score": 65.5,
  "threat_score_components": {
    "socmint_raw": 15.0,
    "socmint_weighted": 4.5,
    "socmint_weight": 0.3
  }
}
```

### 4. Verify Data Types
```bash
# Try numeric operations (should work now)
psql $DATABASE_URL -c "SELECT COUNT(*) FROM alerts WHERE score > 70 AND confidence > 0.8;"

# Check for any TEXT remnants (should be empty)
psql $DATABASE_URL -c "SELECT uuid, score, confidence FROM alerts WHERE score::text ~ '[^0-9.]' LIMIT 5;"
```

## Frontend Updates Required

Now that `source_kind` and `source_tag` are available in the `alerts` table, update your frontend:

### Old Way (Workaround)
```javascript
// Had to check UUID prefix
const isACLED = alert.uuid.startsWith('acled:');
```

### New Way (Direct)
```javascript
// Can now use dedicated field
const isACLED = alert.source_kind === 'intelligence';
const isRSS = alert.source_kind === 'rss';

// Filter by country tag
const nigerianAlerts = alerts.filter(a => a.source_tag === 'country:Nigeria');
```

### SOCMINT Scoring Access
```javascript
// Access SOCMINT breakdown
const components = alert.threat_score_components || {};
const socmintScore = components.socmint_raw || 0;
const socmintContribution = components.socmint_weighted || 0;

// Display
if (socmintScore > 0) {
  console.log(`Alert boosted by +${socmintContribution} from social media intel`);
}
```

## Summary

| Issue | Status | Fix |
|-------|--------|-----|
| Missing `source_kind` in alerts | ✅ Fixed | Migration adds column + backfill |
| Missing `source_tag` in alerts | ✅ Fixed | Migration adds column |
| Missing `threat_score_components` | ✅ Fixed | Migration adds JSONB column |
| `score` as TEXT not NUMERIC | ✅ Fixed | Migration converts type |
| `confidence` as TEXT not NUMERIC | ✅ Fixed | Migration converts type |
| `future_risk_probability` as TEXT | ✅ Fixed | Migration converts type |
| `threat_score` vs `score` mismatch | ✅ Fixed | Code now sets both |
| Missing fields in API responses | ✅ Fixed | Updated SELECT queries |

All files have been updated. **You MUST run the migration** to apply database schema fixes:

```bash
psql $DATABASE_URL -f migrations/003_add_source_metadata_and_fix_types.sql
```

After running the migration, restart your application and the frontend will have proper access to:
- `alert.source_kind` - Direct ACLED vs RSS identification
- `alert.source_tag` - Additional categorization
- `alert.score` - Numeric threat score (0-100)
- `alert.confidence` - Numeric confidence (0-1)
- `alert.threat_score_components` - SOCMINT scoring breakdown
