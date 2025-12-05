# Frontend Verification Checklist

## What Changed on Backend
- ✅ Committed: Fix to `services/threat_engine.py` 
- ✅ Pushed to Railway: `6b2492a`
- **Effect:** Enriched alerts will now have `location_method = 'legacy_precise'` instead of `'unknown'`

## What This Means for Frontend Maps
**Before:** Maps showed 37 alerts (40 filtered out)  
**After:** Maps should show 77 alerts (all enriched ones)

---

## Quick Frontend Checks

### Check 1: Open Maps in Browser
1. Go to your maps page (threat map / travel risk map)
2. Open DevTools → Network tab
3. Look for requests to `/api/map-alerts` or `/api/map-alerts/aggregates`
4. Check the response:
   ```javascript
   // In console:
   fetch('/api/map-alerts').then(r=>r.json()).then(d => {
       console.log('Alerts:', d.items?.length || d.features?.length)
   })
   ```
5. **Before fix:** Should show ~37  
6. **After fix:** Should show ~77

### Check 2: Indonesia Floods (BBC Test)
1. In browser console:
   ```javascript
   fetch('/api/map-alerts').then(r=>r.json()).then(d => {
       const bbc = d.items?.filter(i => i.source?.toLowerCase?.().includes('bbc')) || [];
       console.log('BBC alerts:', bbc.length);
       console.table(bbc.map(a => ({ 
           title: a.title?.substring(0,50), 
           country: a.country,
           method: a.location_method 
       })));
   })
   ```
2. **Should see:** Indonesia flood articles appearing
3. **Should see:** `location_method = 'legacy_precise'` (not 'unknown')

### Check 3: Map Display
1. Zoom to different levels
2. Check if more points appear now
3. Verify Indonesia, Lebanon, Venezuela, etc. showing
4. No crashes or errors in console

### Check 4: Compare Both Endpoints
```javascript
// Test both to see if they're different
Promise.all([
    fetch('/api/map-alerts').then(r=>r.json()),
    fetch('/api/map-alerts/aggregates').then(r=>r.json())
]).then(([individual, aggregated]) => {
    console.log('Individual alerts:', individual.items?.length);
    console.log('Aggregated features:', aggregated.features?.length);
    
    // Should be similar or more in individual now
    if (individual.items?.length >= 77) {
        console.log('✅ FIX WORKING - showing all enriched alerts');
    } else {
        console.log('⚠️ Still showing fewer alerts');
    }
});
```

---

## If Maps Still Show Old Data

### Option 1: Hard Refresh (Clear Cache)
```
Windows/Linux: Ctrl + Shift + R
Mac: Cmd + Shift + R
```

### Option 2: Clear Browser Cache
1. DevTools → Application tab
2. Clear LocalStorage (look for 'map', 'alert' keys)
3. Clear SessionStorage
4. Reload page

### Option 3: Check Backend Is Running
```bash
# From your terminal:
curl https://sentinelairss-production.up.railway.app/api/map-alerts | jq '.items | length'
# Should show: 77+ (or 37 if fix not deployed yet)
```

### Option 4: Wait for Redeployment
- Railway might take 2-5 minutes to redeploy after push
- Check Railway deployment logs
- Wait, then hard refresh browser

---

## What You're Looking For

### ✅ Fix Working:
- [ ] Maps show 77+ alerts (up from 37)
- [ ] Indonesia flood articles visible
- [ ] location_method shows 'legacy_precise' for enriched alerts
- [ ] No console errors
- [ ] Map renders correctly

### ⚠️ Fix Not Working Yet:
- [ ] Still showing 37 alerts
- [ ] BBC articles not visible
- [ ] location_method still 'unknown'
- [ ] → Check: Backend deployed? Cache cleared? Page reloaded?

### ❌ Something Wrong:
- [ ] Console errors
- [ ] Map crashes
- [ ] API returns error
- [ ] → Check: Railway deployment logs, no syntax errors

---

## Backend Status

**Deployed:** Yes (commit 6b2492a pushed)  
**Expected Wait:** 2-5 minutes for Railway to rebuild  
**Changes:** `services/threat_engine.py` lines 1650-1686

**To Verify Backend:**
```bash
# Check if API is running
curl https://sentinelairss-production.up.railway.app/health

# Check map endpoint directly
curl https://sentinelairss-production.up.railway.app/api/map-alerts | jq '.items | length'

# Expected after deployment: 77+
```

---

## The Technical Detail (Why This Works)

**Before:**
```
Alert in database:
- city: "Indonesia"
- country: "Indonesia"
- latitude: -2.5489
- longitude: 113.9213
- location_method: "unknown" ← PROBLEM
↓
Maps query: WHERE location_method IN TIER1_METHODS
↓
"unknown" not in list → FILTERED OUT ✗
```

**After:**
```
Alert in database:
- city: "Indonesia"
- country: "Indonesia"
- latitude: -2.5489
- longitude: 113.9213
- location_method: "legacy_precise" ← FIXED
↓
Maps query: WHERE location_method IN TIER1_METHODS
↓
"legacy_precise" in list → INCLUDED ✓
```

---

## Files to Check If Needed

If maps still not working, the issue might be in frontend:
- `frontend/pages/alerts.js` - How are alerts fetched/displayed?
- `frontend/components/Map.js` - Map rendering logic
- Check if it's using different endpoint than `/api/map-alerts`
- Check if there's frontend-side filtering hiding results

Let me know what you find!
