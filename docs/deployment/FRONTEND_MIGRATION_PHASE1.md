# Frontend Migration Guide - Phase 1 API Changes

## 🚨 Breaking Changes (Immediate Action Required)

### 1. Response Envelope Change
**Before:**
```typescript
// Response was directly itinerary object
{ok: true, itinerary: {...}}
```

**After:**
```typescript
// Response now wrapped in 'data'
{ok: true, data: {...}}
```

**Fix:**
```typescript
// OLD
const response = await createItinerary(data);
const itinerary = response.itinerary;

// NEW
const response = await createItinerary(data);
const itinerary = response.data;
```

### 2. List Response Structure
**Before:**
```typescript
{
  ok: true,
  items: [...],
  itineraries: [...],  // duplicate
  count: 10
}
```

**After:**
```typescript
{
  ok: true,
  data: {
    items: [...],      // only field
    count: 10,         // items returned
    total: 42,         // NEW: total across all pages
    limit: 20,
    offset: 0,
    has_next: true,    // NEW: boolean
    next_offset: 20    // NEW: use this for next page
  }
}
```

**Fix:**
```typescript
// OLD
const {items, count} = response;

// NEW
const {items, count, total, has_next, next_offset} = response.data;
```

### 3. Stats Response
**Before:**
```typescript
{ok: true, count: 42, active: 38, deleted: 4}
```

**After:**
```typescript
{ok: true, data: {total: 42, active: 38, deleted: 4}}
```

**Fix:**
```typescript
// OLD
const {count, active, deleted} = response;

// NEW
const {total, active, deleted} = response.data;
```

### 4. Error Response Structure
**Before:**
```typescript
{error: "Not found"}
```

**After:**
```typescript
{ok: false, error: "Not found", code: "NOT_FOUND"}
```

**Error Codes:**
- `NOT_FOUND` (404)
- `VERSION_CONFLICT` (409)
- `PRECONDITION_FAILED` (412)
- `VALIDATION_ERROR` (400)

## ✨ New Features (Optional Enhancements)

### 1. ETag Support (Recommended)
```typescript
// Save ETag from response headers
const response = await fetch('/api/travel-risk/itinerary/uuid', {
  headers: {'Authorization': `Bearer ${token}`}
});
const etag = response.headers.get('ETag');
const version = response.headers.get('X-Version');
const lastModified = response.headers.get('Last-Modified');

// Use If-Match on updates (preferred over version in body)
await fetch('/api/travel-risk/itinerary/uuid', {
  method: 'PATCH',
  headers: {
    'Authorization': `Bearer ${token}`,
    'If-Match': etag,  // Automatic conflict detection
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({...})
});

// Handle 412 Precondition Failed
if (response.status === 412) {
  const error = await response.json();
  alert('Someone else modified this. Please refresh.');
  // error.current_etag, error.current_version available
}
```

### 2. Conditional GET (Performance Optimization)
```typescript
// Cache the ETag from previous GET
const cachedEtag = localStorage.getItem('itinerary-etag');

const response = await fetch('/api/travel-risk/itinerary/uuid', {
  headers: {
    'Authorization': `Bearer ${token}`,
    'If-None-Match': cachedEtag
  }
});

if (response.status === 304) {
  // Not modified, use cached data
  return cachedData;
}

// Updated, cache new ETag
const newEtag = response.headers.get('ETag');
localStorage.setItem('itinerary-etag', newEtag);
```

### 3. Pagination with has_next
```typescript
// OLD: Manual offset calculation
const nextOffset = offset + limit;

// NEW: Use has_next and next_offset
const {items, has_next, next_offset, total} = response.data;

if (has_next) {
  // Load more with next_offset
  fetchItineraries(limit, next_offset);
}

// Show "10 of 42" in UI
console.log(`Showing ${items.length} of ${total} total`);
```

## 📋 Migration Checklist

### API Client Updates
- [ ] Update all `response.itinerary` → `response.data`
- [ ] Update all `response.items` → `response.data.items`
- [ ] Update all `response.count` → `response.data.total` (for totals)
- [ ] Update stats: `response.count` → `response.data.total`
- [ ] Add error code handling: check `error.code` field
- [ ] Remove references to deprecated `itineraries` field

### Type Definitions
```typescript
// Update interfaces
interface ItineraryResponse {
  ok: true;
  data: Itinerary;  // Not itinerary: Itinerary
}

interface ItineraryListResponse {
  ok: true;
  data: {
    items: Itinerary[];
    count: number;      // returned count
    total: number;      // total across all pages
    limit: number;
    offset: number;
    has_next: boolean;
    next_offset: number | null;
  };
}

interface ItineraryStatsResponse {
  ok: true;
  data: {
    total: number;   // Not count
    active: number;
    deleted: number;
  };
}

interface ErrorResponse {
  ok: false;
  error: string;
  code: 'NOT_FOUND' | 'VERSION_CONFLICT' | 'PRECONDITION_FAILED' | 'VALIDATION_ERROR';
  // Additional fields depending on error type
  current_version?: number;
  expected_version?: number;
  id?: string;
}
```

### Optional: ETag Integration
- [ ] Store ETag from response headers
- [ ] Send If-Match on PATCH/DELETE
- [ ] Handle 412 Precondition Failed
- [ ] Send If-None-Match on GET for 304 support
- [ ] Display X-Version in debug UI

### Testing
- [ ] Test create → verify `response.data` exists
- [ ] Test list → verify `response.data.items` and `has_next`
- [ ] Test update → verify ETag changes
- [ ] Test conflict → verify 409 with VERSION_CONFLICT code
- [ ] Test delete → verify `response.data.deleted`
- [ ] Test stats → verify `response.data.total`

## 🎯 Priority Order

### High (Do First - Breaks Existing Code)
1. Update response parsing: `.itinerary` → `.data`
2. Update list parsing: `.items` → `.data.items`
3. Update stats parsing: `.count` → `.data.total`
4. Update error handling for new structure

### Medium (Improves UX)
1. Use `has_next` for pagination
2. Show "X of Y total" with `total` field
3. Handle structured error codes

### Low (Performance/Polish)
1. Implement ETag caching
2. Use If-Match for updates
3. Implement 304 conditional GET
4. Display version numbers in UI

## 🔧 Example Before/After

### Before
```typescript
async function loadItineraries(offset = 0) {
  const res = await fetch(`/api/travel-risk/itinerary?offset=${offset}`, {
    headers: {'Authorization': `Bearer ${token}`}
  });
  const {items, count} = await res.json();
  setItineraries(items);
  setCount(count);
}
```

### After
```typescript
async function loadItineraries(offset = 0) {
  const res = await fetch(`/api/travel-risk/itinerary?offset=${offset}`, {
    headers: {'Authorization': `Bearer ${token}`}
  });
  const {ok, data} = await res.json();
  if (ok) {
    setItineraries(data.items);
    setTotalCount(data.total);
    setHasMore(data.has_next);
    setNextOffset(data.next_offset);
  }
}
```

## ⏱️ Timeline

- **Immediate:** Update response parsing (breaks existing)
- **This Sprint:** Pagination improvements
- **Next Sprint:** ETag optimization

## 🆘 Support

If issues arise:
1. Check browser console for response structure
2. Verify all `.itinerary` changed to `.data`
3. Check for `.items` vs `.data.items` mistakes
4. Look for error code handling

Backend deployed at: `https://sentinelairss-production.up.railway.app`
