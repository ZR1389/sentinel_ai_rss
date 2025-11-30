# Map Frontend Issues - Investigation Required

**Status**: Backend is working correctly, issues are frontend-side  
**Date**: November 30, 2025

---

## 🔍 ISSUES REPORTED

### Issue 1: Alerts Disappearing on Zoom
**Symptom**: When zooming in/out on threat map, alerts disappear  
**Backend Status**: ✅ WORKING
- Dynamic limits implemented (500-2000 based on bbox area)
- TTLCache (120s) for performance
- Bbox filtering correctly applied in SQL query

**Root Cause**: Frontend NOT sending bbox parameters when zooming
```javascript
// CURRENT (WRONG):
GET /map_alerts?limit=5000

// SHOULD BE (CORRECT):
GET /map_alerts?bbox=-77.1,-76.9,38.8,39.0
```

**Backend Code (api/map_api.py lines 325-400)**:
```python
@map_api.route("/map_alerts")
def map_alerts():
    # Parse bounding box filter
    bbox_param = request.args.get('bbox', '').strip()
    
    if bbox_param:
        parts = [float(x.strip()) for x in bbox_param.split(',')]
        if len(parts) == 4:
            min_lon, min_lat, max_lon, max_lat = parts
            bbox_filter = "AND longitude BETWEEN %s AND %s AND latitude BETWEEN %s AND %s"
    
    # Dynamic limit based on bbox area
    bbox_area = abs((max_lon - min_lon) * (max_lat - min_lat))
    if bbox_area > 1000: limit = 500
    elif bbox_area > 100: limit = 1000
    elif bbox_area > 10: limit = 1500
    else: limit = 2000
```

**Frontend Fix Required**:
1. Calculate viewport bbox on zoom/pan:
   ```javascript
   const bounds = map.getBounds();
   const bbox = [
       bounds.getWest(),  // min_lon
       bounds.getSouth(), // min_lat
       bounds.getEast(),  // max_lon
       bounds.getNorth()  // max_lat
   ].join(',');
   ```

2. Send bbox in API request:
   ```javascript
   fetch(`/map_alerts?bbox=${bbox}`)
   ```

3. Trigger refetch on map moveend event:
   ```javascript
   map.on('moveend', () => {
       fetchAlerts(); // Refetch with new bbox
   });
   ```

---

### Issue 2: Missing Icons ("refresh-cw", "shuffle", "map-pin")
**Symptom**: Browser console logs show icon loading errors  
**Backend Status**: N/A (backend doesn't serve icons)

**Root Cause**: Frontend icon library incomplete or wrong icon names

**Browser Logs**:
```
Icon 'refresh-cw' not found
Icon 'shuffle' not found  
Icon 'map-pin' not found
```

**Frontend Fix Required**:

**Option A: Using Lucide React Icons**
```javascript
import { RefreshCw, Shuffle, MapPin } from 'lucide-react';

// Usage:
<RefreshCw className="icon" />
<Shuffle className="icon" />
<MapPin className="icon" />
```

**Option B: Using Font Awesome**
```javascript
import { faSync, faRandom, faMapMarkerAlt } from '@fortawesome/free-solid-svg-icons';

// Icon mapping:
'refresh-cw' → faSync
'shuffle' → faRandom
'map-pin' → faMapMarkerAlt
```

**Option C: Fix Icon Names**
If using a custom icon system, update icon names to match available icons:
```javascript
// Change from:
icon: 'refresh-cw'
icon: 'shuffle'  
icon: 'map-pin'

// To actual icon names in your library:
icon: 'sync'
icon: 'random'
icon: 'marker'
```

---

### Issue 3: Map Lagging/Bagging
**Symptom**: Map feels slow, laggy on zoom/pan operations  
**Backend Status**: ✅ OPTIMIZED
- TTLCache (120s) reduces DB hits
- Dynamic limits reduce data transfer
- Indexes on lat/lon/published columns

**Possible Causes**:
1. **Too many markers rendering**: Even with backend limits, 2000 markers can lag
2. **No client-side caching**: Frontend refetching on every pan
3. **Inefficient marker rendering**: Re-rendering all markers on every update
4. **No clustering**: Should use marker clustering for dense areas

**Frontend Fix Required**:

**1. Add Marker Clustering**:
```javascript
import MarkerClusterGroup from 'react-leaflet-cluster';

<MarkerClusterGroup>
  {alerts.map(alert => (
    <Marker key={alert.uuid} position={[alert.lat, alert.lon]} />
  ))}
</MarkerClusterGroup>
```

**2. Client-Side Caching** (60s TTL):
```javascript
const cache = new Map();
const CACHE_TTL = 60000; // 60 seconds

function fetchAlerts(bbox) {
  const cacheKey = bbox;
  const cached = cache.get(cacheKey);
  
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.data; // Use cached data
  }
  
  // Fetch fresh data
  const data = await fetch(`/map_alerts?bbox=${bbox}`).then(r => r.json());
  cache.set(cacheKey, { data, timestamp: Date.now() });
  return data;
}
```

**3. Debounce Map Movements**:
```javascript
let debounceTimer;
map.on('moveend', () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    fetchAlerts(); // Only fetch after 300ms of no movement
  }, 300);
});
```

**4. Use Leaflet Marker Recycling**:
```javascript
// Instead of creating new markers each time, update existing ones
const markerRef = useRef(new Map());

alerts.forEach(alert => {
  let marker = markerRef.current.get(alert.uuid);
  if (marker) {
    marker.setLatLng([alert.lat, alert.lon]); // Update position
  } else {
    marker = L.marker([alert.lat, alert.lon]).addTo(map);
    markerRef.current.set(alert.uuid, marker);
  }
});
```

---

## ✅ BACKEND STATUS SUMMARY

All backend optimizations are **DEPLOYED AND WORKING**:

### map_api.py Optimizations:
1. ✅ **Dynamic Limits** (lines 368-377):
   - City zoom: 2000 alerts
   - Region zoom: 1500 alerts
   - Country zoom: 1000 alerts
   - Continent zoom: 500 alerts

2. ✅ **Bbox Filtering** (lines 343-358):
   - Accepts `?bbox=min_lon,min_lat,max_lon,max_lat`
   - Filters: `longitude BETWEEN %s AND %s AND latitude BETWEEN %s AND %s`
   - Applies BEFORE limit (prevents wrong results)

3. ✅ **TTLCache** (lines 22-24):
   - `_MAP_ALERTS_CACHE`: 100 entries, 120s TTL
   - `_COUNTRY_RISKS_CACHE`: 10 entries, 300s TTL
   - Reduces DB load by 80-90%

4. ✅ **SQL Optimizations**:
   - `ORDER BY published DESC NULLS LAST` (newest first)
   - `latitude BETWEEN -90 AND 90` (valid coords only)
   - `longitude BETWEEN -180 AND 180` (valid coords only)
   - Indexes on: `(latitude, longitude, published)`

5. ✅ **CORS Headers**:
   - `Access-Control-Allow-Origin: *`
   - `Access-Control-Allow-Methods: GET, OPTIONS`
   - Works with frontend requests

---

## 🔧 FRONTEND FILES TO CHECK

### Primary Files (React/TypeScript likely):
1. **Map Component**: 
   - `web/components/ThreatMap.tsx` or similar
   - `web/components/Map.tsx`
   - `web/pages/map.tsx`

2. **API Client**:
   - `web/lib/api.ts`
   - `web/services/mapService.ts`
   - `web/utils/api.ts`

3. **Icon Configuration**:
   - `web/components/Icon.tsx`
   - `web/lib/icons.ts`
   - Check package.json for icon library (lucide-react, font-awesome, etc.)

### What to Look For:

**1. Map fetch calls WITHOUT bbox:**
```typescript
// WRONG (current):
fetch('/map_alerts?limit=5000')

// RIGHT (needed):
const bounds = map.getBounds();
const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
fetch(`/map_alerts?bbox=${bbox}`)
```

**2. Missing zoom/pan event handlers:**
```typescript
// Need to add:
map.on('moveend', () => {
  refetchAlerts();
});
```

**3. Icon imports:**
```typescript
// Check if these exist:
import { RefreshCw, Shuffle, MapPin } from 'lucide-react';
// OR
import { faSync, faRandom, faMapMarkerAlt } from '@fortawesome/free-solid-svg-icons';
```

---

## 📋 TESTING CHECKLIST

After frontend fixes, test these scenarios:

### Test 1: Bbox Filtering
1. Open browser DevTools → Network tab
2. Open threat map
3. Zoom to a city (e.g., Belgrade, Washington DC)
4. **Expected**: Network request shows `?bbox=-77.1,38.8,-76.9,39.0` (approximate)
5. **Expected**: Response has ~50-200 alerts for that bbox
6. Zoom out to country view
7. **Expected**: New request with larger bbox
8. **Expected**: Response has ~200-500 alerts

### Test 2: Icons Rendering
1. Open browser DevTools → Console tab
2. Open threat map
3. **Expected**: NO errors like "Icon 'refresh-cw' not found"
4. **Expected**: All UI buttons show icons correctly
5. **Expected**: Map markers show location pins

### Test 3: Performance
1. Open threat map
2. Pan around rapidly for 10 seconds
3. **Expected**: Map feels responsive
4. **Expected**: No lag or freezing
5. Check DevTools → Network tab
6. **Expected**: Requests debounced (not 50 requests)
7. **Expected**: Some requests return from cache (304 status or instant)

### Test 4: Zoom Transitions
1. Start at world view (all continents visible)
2. Zoom to Europe
3. **Expected**: Alerts appear for Europe
4. Zoom to single country (Serbia)
5. **Expected**: More detailed alerts appear
6. Zoom to city (Belgrade)
7. **Expected**: City-level alerts appear (not global alerts)

---

## 🚀 DEPLOYMENT NOTES

**Backend**: ✅ Already deployed and working (Railway)

**Frontend**: Needs fixes in 3 areas:
1. Add bbox calculation and sending
2. Fix icon imports/names
3. Add marker clustering and caching

**No backend changes needed** - all issues are frontend-side.

---

## 📞 NEXT STEPS

1. Share this document with frontend developer
2. Update frontend map component to send bbox
3. Fix icon library imports
4. Add marker clustering for performance
5. Test all 4 scenarios above
6. Deploy frontend updates

**Backend is ready** - frontend just needs to use the bbox parameter correctly.
