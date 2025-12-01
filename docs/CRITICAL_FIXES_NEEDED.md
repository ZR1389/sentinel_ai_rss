# CRITICAL SYSTEM ISSUES - IMMEDIATE FIX REQUIRED

**Status**: System producing low-quality, duplicate, and incorrectly-located alerts  
**Priority**: URGENT - System unusable in current state  
**Date**: November 30, 2025

---

## 🚨 CRITICAL PROBLEMS IDENTIFIED

### Problem 1: **Duplicate Alerts** (5x same article)
**Symptom**: "This is not 1986..." appearing 5 times  
**Root Cause**: UUID based on `source|title|link` - same article from different RSS feeds creates different UUIDs  
**Impact**: Database bloated with duplicates, user experience ruined

**Current Code**:
```python
def _uuid_for(source: str, title: str, link: str) -> str:
    return _sha(f"{source}|{title}|{link}")  # ❌ WRONG - source makes each UUID unique
```

**Fix Required**: Use `title|link` ONLY for UUID (ignore source)
```python
def _uuid_for(source: str, title: str, link: str) -> str:
    return _sha(f"{title}|{link}")  # ✅ CORRECT - same article = same UUID
```

---

### Problem 2: **Wrong Locations** ("Rio De Janeiro, United States")
**Symptom**: Brazilian city marked as USA  
**Root Cause**: Multiple location extraction bugs:
1. Global feeds have NO city/country tags → extraction from content fails
2. Location extraction falls back to random words in text
3. No validation that city actually belongs to country
4. Coordinates don't match city/country pair

**Examples Found**:
- Rio De Janeiro, United States ❌
- Paris, United States ❌ (probably from "Paris, Texas" extraction bug)
- Beijing, United Kingdom ❌

**Fix Required**: 
1. Add strict location validation
2. Verify city exists in country before accepting
3. Reject alerts with impossible city/country combinations
4. Use coordinate-to-country reverse lookup for validation

---

### Problem 3: **Missing Critical Alerts** (DC National Guard Attack)
**Symptom**: Real threats (Afghan attack on National Guard in DC) NOT captured  
**Root Cause**: Keyword filtering TOO STRICT
1. FBI feeds filtered at ~80% (should be 20%)
2. Critical terms missing from threat_keywords.json
3. "National Guard" not in threat keywords
4. Military attack keywords weak

**Missing Keywords**:
- National Guard
- Military personnel
- Service members
- Armed forces attack
- Military facility
- Defense personnel
- Soldier killed/wounded

**Fix Required**:
1. Add military/defense keywords
2. Reduce FBI filtering (current 80% → target 20%)
3. Prioritize US domestic security events
4. Add "attack on [military/police/government]" patterns

---

### Problem 4: **Low Quality Alerts Flooding System**
**Symptom**: Sports, entertainment, politics noise in threat database  
**Examples**:
- "Australian prime minister becomes first to wed in office" ❌
- "Flamengo beat Palmeiras to win Copa Libertadores" ❌  
- "Pope visits Blue Mosque" ❌
- "Wiggles issue statement after appearing in Ecstasy music video" ❌

**Root Cause**: Weak threat scoring + permissive RSS filtering

**Fix Required**:
1. Raise minimum score threshold (current: 20 → new: 40)
2. Add content-type detection (sports, entertainment, politics)
3. Block non-threat categories at RSS stage
4. Improve threat_scorer.py scoring accuracy

---

### Problem 5: **Map Performance Issues**
**Symptom**: Alerts disappear on zoom, laggy map  
**Root Cause**: Frontend still using old `/map_alerts` endpoint (broken), not new `/api/map-alerts`

**Browser Logs**:
```
[ThreatMap][Fetch] GET /api/map-alerts/aggregates?days=99999&limit=5000&by=country
[ThreatMap] Data received. features: 35
[ThreatMap] Stable zoom mode changed: aggregates → detail (zoom 12)
[ThreatMap][Fetch] GET /api/map-alerts?days=99999&limit=5000
[ThreatMap] Backend Response: Object
[ThreatMap] Data received. features: 166
```

**Issues**:
1. Using `/api/map-alerts` (lowercase) not `/api/map-alerts` (correct endpoint)
2. No bbox parameter being sent on zoom → returns global data every time
3. Cache not working (every zoom refetches)

**Fix Required**: Frontend must send bbox on zoom:
```javascript
// WRONG (current):
GET /api/map-alerts?days=99999&limit=5000

// CORRECT (needed):
GET /api/map-alerts?days=99999&limit=5000&min_lon=-77.1&max_lon=-76.9&min_lat=38.8&max_lat=39.0
```

---

## 📋 IMPLEMENTATION PLAN

### Phase 1: STOP THE BLEEDING (1 hour)
**Priority**: Prevent more garbage from entering database

1. **Fix Deduplication** (10 min)
   - Change UUID to use `title|link` only
   - Deploy immediately

2. **Raise Quality Bar** (20 min)
   - Minimum score: 20 → 50
   - Add content-type blocking (sports, entertainment)
   - Deploy immediately

3. **Fix Location Validation** (30 min)
   - Add city-country validation check
   - Reject impossible combinations
   - Deploy immediately

---

### Phase 2: FIX MISSING ALERTS (2 hours)
**Priority**: Capture critical threats being missed

1. **Expand Military Keywords** (30 min)
   - Add National Guard, military personnel, armed forces
   - Add attack patterns for military/government targets
   - Test with DC National Guard attack

2. **Fix FBI Filtering** (30 min)
   - Reduce filtering from 80% to 20%
   - Prioritize domestic security events
   - Test with recent FBI alerts

3. **Add Priority Patterns** (60 min)
   - "Attack on [military/police/government facility]"
   - "Shooting at [military base/federal building]"
   - "[Number] killed in [attack/shooting]"
   - Auto-boost scores for priority patterns

---

### Phase 3: DATABASE CLEANUP (4 hours)
**Priority**: Remove existing garbage

1. **Delete Duplicates** (2 hours)
   ```sql
   -- Find duplicates by title similarity
   DELETE FROM alerts WHERE id IN (
     SELECT id FROM (
       SELECT id, title, 
         ROW_NUMBER() OVER (PARTITION BY title ORDER BY published DESC) as rn
       FROM alerts
     ) t WHERE rn > 1
   );
   ```

2. **Delete Wrong Locations** (1 hour)
   ```sql
   -- Delete alerts with impossible city/country combinations
   DELETE FROM alerts WHERE 
     (city = 'Rio De Janeiro' AND country != 'Brazil') OR
     (city = 'Paris' AND country NOT IN ('France', 'United States')) OR
     (city LIKE '%Beijing%' AND country != 'China');
   ```

3. **Delete Low-Quality Alerts** (1 hour)
   ```sql
   -- Delete sports, entertainment, politics
   DELETE FROM alerts WHERE 
     title ~* 'win|beat|score|match|game|election|president|minister|pope|wedding';
   ```

---

### Phase 4: FIX FRONTEND (2 hours)
**Priority**: Make map work properly

1. **Add bbox to Map Requests** (1 hour)
   - Calculate viewport bbox on zoom
   - Send min_lon, max_lon, min_lat, max_lat
   - Test with Belgrade zoom

2. **Fix Endpoint URL** (30 min)
   - Change `/api/map-alerts` to `/api/map-alerts` (if needed)
   - Verify correct endpoint being called

3. **Add Client-Side Caching** (30 min)
   - Cache responses by bbox
   - 60s TTL for same viewport
   - Reduce server load

---

## 🎯 SUCCESS CRITERIA

### After Fixes, System Should:
1. ✅ NO duplicate alerts (same title = 1 alert only)
2. ✅ NO impossible locations (Rio in Brazil, not USA)
3. ✅ CAPTURE critical events (DC National Guard attack)
4. ✅ NO sports/entertainment/politics noise
5. ✅ Map works smoothly (no disappearing alerts)
6. ✅ Quality alerts only (score ≥ 50)

---

## 📊 VERIFICATION TESTS

### Test 1: Deduplication
```bash
# Should return 0 duplicates
railway run psql $DATABASE_URL -c "
  SELECT title, COUNT(*) as cnt 
  FROM alerts 
  GROUP BY title 
  HAVING COUNT(*) > 1 
  ORDER BY cnt DESC 
  LIMIT 10;
"
```

### Test 2: Location Validation
```bash
# Should return 0 wrong locations
railway run psql $DATABASE_URL -c "
  SELECT city, country, COUNT(*) 
  FROM alerts 
  WHERE (city = 'Rio De Janeiro' AND country != 'Brazil')
     OR (city = 'Paris' AND country NOT IN ('France', 'United States'))
  GROUP BY city, country;
"
```

### Test 3: Quality Check
```bash
# Should return ONLY threat-related content
railway run psql $DATABASE_URL -c "
  SELECT title, score 
  FROM alerts 
  WHERE published >= NOW() - INTERVAL '24 hours' 
  ORDER BY score DESC 
  LIMIT 20;
"
```

### Test 4: Critical Event Capture
```bash
# Should find DC National Guard attack if it happened recently
railway run psql $DATABASE_URL -c "
  SELECT title, city, country, score 
  FROM alerts 
  WHERE title ~* 'national guard|military attack|soldier' 
    AND country = 'United States' 
  ORDER BY published DESC 
  LIMIT 10;
"
```

---

## ⚠️ DEPLOYMENT ORDER

**MUST follow this order to avoid making things worse:**

1. Deploy deduplication fix (prevents new duplicates)
2. Deploy location validation (prevents new wrong locations)
3. Deploy quality filters (prevents new garbage)
4. Run database cleanup (removes existing garbage)
5. Deploy frontend fixes (makes map work)
6. Monitor for 24h and adjust thresholds

---

## 🔧 FILES TO MODIFY

### Backend:
1. `services/rss_processor.py` - deduplication, location validation, quality filters
2. `config/threat_keywords.json` - add military/government keywords
3. `services/threat_scorer.py` - improve scoring logic
4. `api/map_api.py` - verify bbox handling

### Frontend:
1. `components/ThreatMap.tsx` - add bbox calculation and sending
2. `lib/api.ts` - fix endpoint URLs

### Database:
1. Run cleanup SQL scripts (in deployment order)

---

**READY TO IMPLEMENT?** Let me know and I'll fix these issues one by one.
