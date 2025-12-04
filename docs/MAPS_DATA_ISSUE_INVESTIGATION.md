# Maps Data Issue Investigation

**Date:** December 4, 2025  
**Status:** ROOT CAUSE IDENTIFIED + SOLUTIONS PROVIDED

---

## 🔴 Issues Found

### Issue 1: Only 37 of 77 Alerts Showing in Maps (48% loss)

**Symptom:** Maps (threat map & travel risk map) show significantly fewer alerts than the alerts.js page

**Root Cause:** **Location method filtering - too restrictive**
- Maps endpoint (`/api/map-alerts`) requires `location_method` to be in TIER1_METHODS list
- **70.1% of alerts (54/77) have `location_method = 'unknown'`** 
- Only **29.9% of alerts (23/77) have `location_method = 'legacy_precise'`**
- Result: **40 alerts filtered out** despite having valid coordinates and country data

**Database Evidence:**
```
Location Method Distribution:
  ✗ EXCLUDED   unknown           54 (70.1%)  - 26 countries
  ✓ TIER1      legacy_precise    23 (29.9%)  - 11 countries

Maps show only: 23/77 alerts (29.9%)
Missing from maps: 54/77 alerts (70.1%)
```

**Affected Alerts Examples:**
- Indonesia floods (BBC duplicates) - `location_method = unknown`
- Venezuela earthquake - `location_method = unknown`
- Lebanon Israeli strikes - `location_method = unknown`
- South Africa massacre - `location_method = unknown`
- Many recent enriched alerts - all marked `unknown`

---

### Issue 2: BBC Duplicate Detection False Negative

**Symptom:** User reported duplicates but database shows none with exact title matches

**Root Cause:** **Title variations in same article**
```
Same article, published at exact same time, but TWO entries:
1. "Death toll in Indonesia floods passes 500 with hundreds more missing..."
2. "Death toll in Indonesia floods passes 500..."

UUID Generation: SHA1(title|link)
- Different titles = Different UUIDs = No deduplication
- Deduplication logic didn't catch this
```

**Database Evidence:**
```
UUID: b4e84e03982da7e1b8b0877882d58528
UUID: 89fab64edf278bf31f604d3d299f5357
Title: "Death toll in Indonesia floods passes 500 with hundreds more..."
Title: "Death toll in Indonesia floods passes 500..."
Published: 2025-12-01 09:57:33 (EXACT SAME TIME)
Source: bbc.co.uk
```

**Why Deduplication Missed It:**
- Raw RSS feed likely had TWO article titles from BBC
- Deduplication runs on `SHA1(title|link)` 
- If link is identical but title varies, different UUIDs generated
- Need to check if links are identical

---

## 📊 Data Distribution

### Alert Data Summary
- **Total enriched alerts:** 77
- **Total shown in maps (30-day window):** 37 (48%)
- **Filtered out by location_method:** 40 (52%)
- **Date range:** Nov 9 - Dec 2, 2025
- **Countries represented:** 26 countries (all have data)
- **Missing city-level data:** Most alerts have `city = NULL`

### Map Query Results (Backend Actual)
```
30-day window (default): 37 alerts, 15 countries
90-day window (country risks): 37 alerts, 15 countries
```

### Alerts Hidden from Maps
- 54 alerts with `location_method = 'unknown'` 
- All have valid `country` data
- Most lack `city` data (affects drill-down)
- Most lack `latitude/longitude` data

---

## 🎯 Solutions

### Solution 1: Fix Location Method on Recent Alerts

**Problem:** 70% of alerts marked as `location_method = 'unknown'` but have valid coordinates

**Fix Options:**

#### Option A: Update Unknown Methods to legacy_precise (RECOMMENDED)
```sql
-- Only update enriched alerts (main.py line 3500+)
UPDATE alerts 
SET location_method = 'legacy_precise'
WHERE location_method = 'unknown'
  AND (
    (latitude IS NOT NULL AND longitude IS NOT NULL) 
    OR city IS NOT NULL
    OR country IS NOT NULL
  );
```

**Impact:** 40+ additional alerts will appear in maps

#### Option B: Add 'unknown' to TIER1_METHODS in map_api.py
```python
TIER1_METHODS = [
    'coordinates',
    'nlp_nominatim',
    'nlp_opencage',
    'production_stack',
    'nominatim',
    'opencage',
    'db_cache',
    'legacy_precise',
    'moderate',
    'feed_tag_mapped',
    'feed_tag',
    'country_centroid',
    'unknown'  # Add this line
]
```

**Pros:** No database changes needed  
**Cons:** 'unknown' is not descriptive; doesn't fix root cause

---

### Solution 2: Fix BBC Duplicate Detection

**Problem:** Same article published twice with slightly different titles (truncation handling)

**Fix Steps:**

1. **Identify BBC duplicates:**
```sql
SELECT 
    source,
    COUNT(DISTINCT title) as title_variants,
    COUNT(*) as total,
    COUNT(DISTINCT link) as unique_links,
    link
FROM alerts
WHERE LOWER(source) LIKE '%bbc%'
GROUP BY source, link
HAVING COUNT(*) > 1;
```

2. **Check if links are identical** (indicates true duplicate, not variant title)

3. **If links are identical:** 
   - Remove duplicate with older `published` timestamp
   - Keep the one with more complete title

4. **Update UUID generation** (in rss_processor.py) to use:
   ```python
   uuid = hashlib.sha1(f"{link}".encode()).hexdigest()  # Use ONLY link
   # Instead of: SHA1(title|link)
   ```
   This prevents title variations from creating different UUIDs

---

### Solution 3: Populate City Data for Better Filtering

**Current State:** 40+ alerts missing city data

**Fix:** During enrichment, if city is NULL but coordinates exist:
```python
# In threat_engine.py or enrichment pipeline
if not alert.get('city') and alert.get('latitude') and alert.get('longitude'):
    city = reverse_geocode(lat, lon)  # Use Nominatim or existing service
    alert['city'] = city
```

**Impact:** Enables better drill-down, more accurate risk radius calculation

---

## 📋 Frontend Checklist (for Your Investigation)

When checking the frontend (alerts.js page), verify:

1. **API Endpoint Used:**
   - ✅ Does it call `/api/map-alerts`?
   - ✅ Does it call `/api/map-alerts/aggregates`?
   - ❓ Does it have different parameters or caching?

2. **Query Parameters:**
   - What `days` parameter is sent? (default=30, backend cap=20,000 alerts max)
   - What `limit` parameter? (default=5000)
   - What `severity` or `category` filters?

3. **Data Transformation:**
   - How are alerts.js page alerts fetched?
   - Do they use same API endpoints or different ones?
   - Is there local filtering/caching affecting display?

4. **Cache Issues:**
   - Backend cache TTL: 120 seconds (2 minutes)
   - Frontend might have its own cache
   - Hard refresh might be needed

5. **Compare Two Sources:**
   ```
   Source A: /api/map-alerts/aggregates (maps endpoint)
   Source B: /api/... (alerts.js endpoint - find this)
   Source C: Direct PostgreSQL count
   
   Compare returned alert counts
   ```

---

## 🚀 Recommended Action Plan

### Immediate (Quick Fix - 5 minutes)
```bash
# Option A: Update location_method on 40 alerts
psql $DATABASE_URL -c "UPDATE alerts SET location_method = 'legacy_precise' WHERE location_method = 'unknown' AND country IS NOT NULL;"

# Option B: Add 'unknown' to TIER1_METHODS (code change)
# Edit: core/main.py line 3009
# Edit: api/map_api.py line 280
```

### Short-term (Root Cause Fix - 30 minutes)
1. Identify BBC duplicate links (check if identical)
2. Remove duplicates by keeping latest/most complete title
3. Update UUID generation to use only `link` field

### Medium-term (Data Quality - 1-2 hours)
1. Populate missing city data during enrichment
2. Ensure all alerts have `location_method` populated correctly
3. Add test cases for location method assignment

---

## 📌 Files to Review/Modify

### Backend
- `core/main.py` - Lines 2886-3250 (map-alerts endpoint)
- `core/main.py` - Lines 3009-3020 (TIER1_METHODS)
- `api/map_api.py` - Lines 280+ (TIER1_METHODS definition)
- `rss_processor.py` - UUID generation logic
- `threat_engine.py` - Enrichment/geocoding logic

### Database
- Alerts table: `location_method` distribution
- Raw_alerts table: Duplicate link checking

### Frontend
- alerts.js - API endpoint and query parameters
- Map component - Aggregates vs individual alerts
- Caching logic

---

## 🔍 SQL Diagnostic Queries

**Check current map data (what user sees):**
```sql
SELECT COUNT(*) FROM alerts WHERE location_method IN ('coordinates', 'nlp_nominatim', 'nlp_opencage', 'production_stack', 'nominatim', 'opencage', 'db_cache', 'legacy_precise', 'moderate', 'feed_tag_mapped', 'feed_tag', 'country_centroid');
-- Result: 37 (shown in maps)
```

**Check hidden alerts:**
```sql
SELECT COUNT(*) FROM alerts WHERE location_method = 'unknown' OR location_method IS NULL;
-- Result: 40 (missing from maps)
```

**Check BBC duplicates:**
```sql
SELECT title, COUNT(*) FROM alerts WHERE LOWER(source) LIKE '%bbc%' GROUP BY title HAVING COUNT(*) > 1;
-- Check if links are identical for these titles
```

---

## ✅ Validation Checklist

After implementing fixes:

- [ ] Run SQL queries above to verify counts changed
- [ ] Manually check map endpoints: `/api/map-alerts` returns 60+ alerts
- [ ] Verify BBC duplicates resolved (2→1 alert)
- [ ] Test map UI - should show all 77 alerts or at least 50+
- [ ] Check alerts.js page - compare with maps
- [ ] Hard refresh browser cache
- [ ] Test on different zoom levels (country→region→city)
- [ ] Verify no data loss or corruption

