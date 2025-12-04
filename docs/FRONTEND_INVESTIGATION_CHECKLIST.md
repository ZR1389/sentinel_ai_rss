# Frontend Investigation Checklist

## 🎯 What to Check in alerts.js

### 1. **API Endpoint Used**
Look for these patterns in alerts.js:

```javascript
// Find where map alerts are fetched
// Search for:
fetch('/api/map-alerts')      // Raw individual alerts
fetch('/api/map-alerts/aggregates')  // Country/region/city groups
fetch('/api/...')  // Other endpoints?

// Note the full URL pattern
```

**Questions to answer:**
- Which endpoint(s) does alerts.js page use?
- Does it use `/api/map-alerts` or different endpoint?
- Are there multiple calls (aggregates + details)?

---

### 2. **Query Parameters Sent**
When you find the fetch call, check parameters:

```javascript
// Look for query strings like:
fetch('/api/map-alerts?days=30&limit=5000&severity=high')
fetch('/api/map-alerts?country=Indonesia')
fetch('/api/map-alerts?category=terrorism')

// Common params to find:
- days=?    (default backend: 30)
- limit=?   (default backend: 5000) 
- severity=?
- category=?
- country=?
- region=?
- city=?
- travel=?
```

**Check for:**
- Does it send `days=` parameter? What value?
- Does it filter by severity/category?
- Does it filter by region/country?
- Hard-coded filters that differ from backend defaults?

---

### 3. **Response Processing**
Look for how the response is processed:

```javascript
// After fetch completes
.then(response => response.json())
.then(data => {
    // How is data handled?
    // How many alerts does data contain?
    // Are there any filters/transformations applied?
    // Is data stored in state/cache?
    console.log('Alerts received:', data.items.length)  // Or similar
})
```

**Check for:**
- How many items are logged?
- Is there filtering applied after fetch?
- Is data cached locally?
- Cache invalidation logic?

---

### 4. **Compare Two Views**

Create a simple test to show both:

```javascript
// In browser console on alerts.js page:

// 1. Fetch from maps endpoint
fetch('/api/map-alerts?days=30').then(r => r.json()).then(d => {
    console.log('MAP ENDPOINT: ' + d.items.length + ' alerts');
    return d.items;
})

// 2. Fetch what alerts.js shows  
// (find the exact endpoint it uses)
fetch('/api/...(whatever alerts.js uses)').then(r => r.json()).then(d => {
    console.log('ALERTS.JS ENDPOINT: ' + d.items.length + ' alerts');
    return d.items;
})

// 3. Compare
// Are they the same endpoint?
// Same number of alerts?
```

---

### 5. **Network Inspector**
Use browser DevTools → Network tab:

1. Open alerts.js page
2. Open Network tab
3. Look for XHR/Fetch requests
4. Find the request to `/api/map-alerts` or similar
5. Click on it and check:
   - **Request URL** - what parameters?
   - **Response** - how many items? Check `items.length` or `features.length`
   - **Response time** - how long?
   - **Cache headers** - is it cached?

**Copy the full URL to check manually:**
```
Visit in browser or curl:
https://your-domain/api/map-alerts?<parameters>

Compare results with:
https://your-domain/api/map-alerts  (no parameters)
```

---

### 6. **Map Component Parameters**
If alerts.js displays a Mapbox/Leaflet map, look for:

```javascript
// Zoom level settings
map.setZoom(level)

// Event handlers
map.on('zoomend', () => { /* refetch? */ })

// Aggregates vs individual alerts based on zoom?
if (zoom < 5) {
    fetch('/api/map-alerts/aggregates')  // Countries
} else if (zoom < 10) {
    fetch('/api/map-alerts/aggregates?by=region')  // Regions
} else {
    fetch('/api/map-alerts')  // Individual points
}
```

**Check for:**
- Different API calls based on zoom level?
- Aggregates endpoint used?
- Frontend filter logic for zoom levels?

---

### 7. **Caching Logic**
Look for cache-related patterns:

```javascript
// LocalStorage cache?
localStorage.getItem('mapAlerts')
localStorage.setItem('mapAlerts', data)

// Session storage?
sessionStorage.getItem('mapAlerts')

// In-memory cache?
let cachedAlerts = null
if (cachedAlerts) return cachedAlerts

// API response cache headers?
// Check Network tab → Response Headers
// Look for: Cache-Control, ETag, Last-Modified
```

**To test:**
1. Open alerts.js page
2. Open DevTools → Application → LocalStorage/SessionStorage
3. Look for keys containing 'map', 'alert', 'geo'
4. Do they have stale data?
5. Hard refresh: `Ctrl+Shift+R` (Linux/Windows) or `Cmd+Shift+R` (Mac)
6. Check if map updates

---

### 8. **Error Handling**
Look for what happens when API fails:

```javascript
// Error cases:
.catch(error => {
    console.error('Failed to fetch:', error)
    // Falls back to old data? Shows error? Returns empty?
})

// Status code handling:
if (!response.ok) {
    // What does it do? 
    // Shows cached data? Returns empty?
    // Shows error message?
}
```

---

## 🧪 Testing Steps

### Test 1: Direct API Check
```bash
# From terminal, check backend directly:
curl https://sentinelairss-production.up.railway.app/api/map-alerts | jq '.items | length'
curl https://sentinelairss-production.up.railway.app/api/map-alerts/aggregates | jq '.features | length'

# Expected: Should show 37-40+ alerts now (was 37 before fix)
```

### Test 2: Browser Console Test
```javascript
// In browser console on alerts.js page:

// Get actual endpoint response
fetch('/api/map-alerts?days=30').then(r=>r.json()).then(d => {
    console.table({
        'Endpoint': '/api/map-alerts',
        'Alert Count': d.items?.length || d.features?.length,
        'Countries': d.items?.map(i => i.country).filter((v,i,a)=>a.indexOf(v)===i).length,
        'Response Time': new Date().toLocaleTimeString()
    })
})

// Check for BBC duplicates
fetch('/api/map-alerts?days=30').then(r=>r.json()).then(d => {
    const bbc = d.items?.filter(i => i.source.toLowerCase().includes('bbc')) || []
    console.log('BBC alerts found:', bbc.length)
    console.table(bbc.map(a => ({ title: a.title.substring(0,50), source: a.source, published: a.published })))
})
```

### Test 3: Compare Endpoints
```javascript
// Terminal (create compare.html and open in browser):
async function compare() {
    const r1 = await fetch('/api/map-alerts').then(r=>r.json());
    const r2 = await fetch('/api/map-alerts/aggregates').then(r=>r.json());
    console.log('Individual alerts:', r1.items?.length);
    console.log('Aggregated alerts:', r2.features?.length);
}
compare()
```

---

## 📝 Report Template

When you find the issue, document:

```
FRONTEND FINDINGS:

Endpoint(s) Used:
- [URL and parameters]

Number of Alerts Shown:
- alerts.js page: ___ alerts
- API endpoint directly: ___ alerts
- Backend database: 77 total (37 with proper location method, 40 with unknown)

Query Parameters:
- days: ___
- limit: ___
- filters: ___

Caching:
- LocalStorage cached? Yes/No
- SessionStorage cached? Yes/No
- Browser cache TTL: ___
- Does hard refresh help? Yes/No

BBC Duplicates Shown?
- alerts.js page: ___ BBC articles
- Direct API: ___ BBC articles

Difference Explanation:
- [Why do maps show fewer alerts?]
- [Same API? Different params? Cache issue? Filtering?]
```

---

## 💡 If You Find The Problem

Once you identify why maps show fewer alerts:

### If it's a **Cache Issue:**
→ Backend needs cache invalidation OR frontend needs cache busting

### If it's a **Different Endpoint:**
→ Both endpoints need alignment (same filtering)

### If it's a **Frontend Filtering:**
→ Backend should match frontend assumptions

### If it's a **Parameter Difference:**
→ Document the parameter and apply to both endpoints

---

## 🔗 Backend Reference Points

**These are already checked/working on backend:**

✅ `/api/map-alerts` endpoint exists (core/main.py line 2886)  
✅ Returns 37 alerts (30-day window) in test  
✅ Uses `location_method = 'unknown' OR legacy_precise` filtering  
✅ Should return 60+ alerts after fix  

**After backend fix applied:**
- 54 alerts will gain `location_method = 'legacy_precise'`
- Maps endpoint will show 77 alerts (all enriched)
- BBC duplicates will be reduced to 1

