# Travel Risk Itinerary Backend Implementation

## Overview
Implemented database-backed travel risk itinerary persistence with full CRUD operations, authentication, and proper bounds sanitization.

## Changes Made

### 1. Database Migration (`migrations/004_travel_risk_itineraries.sql`)
Created `travel_itineraries` table with:
- **Columns**: id, user_id, itinerary_uuid, title, description, data (JSONB), created_at, updated_at, is_deleted, deleted_at, version
- **Indexes**:
  - `idx_itineraries_user_created` - Fast dashboard listing (user_id, created_at DESC)
  - `idx_itineraries_uuid` - UUID lookups
  - `idx_itineraries_user_active` - Active itineraries by user
- **Triggers**: Auto-update `updated_at` timestamp on changes
- **View**: `active_itineraries` - Join with users table for easy queries
- **Features**: Soft delete, version tracking, JSONB data storage for flexibility

**Data Structure Expected in JSONB**:
```json
{
  "waypoints": [...],
  "routes": [...],
  "risk_analysis": {...},
  "metadata": {...}
}
```

### 2. Itinerary Manager Module (`utils/itinerary_manager.py`)
Core utility functions with proper connection pooling:

**Functions**:
- `create_itinerary(user_id, data, title, description)` - Create new itinerary
- `list_itineraries(user_id, limit=20, offset=0, include_deleted=False)` - List with pagination
- `get_itinerary(user_id, itinerary_uuid, include_deleted=False)` - Get single itinerary
- `update_itinerary(user_id, itinerary_uuid, data, title, description)` - Update (increments version)
- `delete_itinerary(user_id, itinerary_uuid, soft=True)` - Soft or permanent delete
- `get_itinerary_stats(user_id)` - Get counts (total, active, deleted)

**Features**:
- Uses `db_utils` connection pool
- RealDictCursor for dict-based results
- Proper error handling and logging
- Validates data structure (requires 'waypoints' field)

### 3. Enhanced `/api/travel-risk/assess` Endpoint
**Bounds Sanitization**:
```python
radius_km = max(1, min(radius_km, 500))  # Clamp 1-500 km
days = max(1, min(days, 365))            # Clamp 1-365 days
```

Prevents excessive database queries and ensures reasonable API usage.

### 4. New API Endpoints (main.py)

#### POST `/api/travel-risk/itinerary`
Create new itinerary
- **Auth**: JWT required (`@login_required`)
- **Body**: `{data: {...}, title?: string, description?: string}`
- **Returns**: `201 {ok: true, itinerary: {...}}`
- **Errors**: `400` (validation), `500` (server error)

#### GET `/api/travel-risk/itinerary`
List user's itineraries
- **Auth**: JWT required
- **Query**: `?limit=20&offset=0&include_deleted=false`
- **Returns**: `200 {ok: true, itineraries: [...], count, limit, offset}`
- **Features**: Pagination, soft-delete filtering

#### GET `/api/travel-risk/itinerary/:uuid`
Get specific itinerary
- **Auth**: JWT required
- **Returns**: `200 {ok: true, itinerary: {...}}`
- **Errors**: `404` (not found)

#### PATCH `/api/travel-risk/itinerary/:uuid`
Update itinerary
- **Auth**: JWT required
- **Body**: `{data?: {...}, title?: string, description?: string}`
- **Returns**: `200 {ok: true, itinerary: {...}}`
- **Features**: Increments version number, updates `updated_at`

#### DELETE `/api/travel-risk/itinerary/:uuid`
Delete itinerary
- **Auth**: JWT required
- **Query**: `?permanent=false`
- **Returns**: `200 {ok: true, deleted: true, permanent: boolean}`
- **Features**: Soft delete by default, optional permanent deletion

#### GET `/api/travel-risk/itinerary/stats`
Get user's itinerary statistics
- **Auth**: JWT required
- **Returns**: `200 {ok: true, total, active, deleted}`

## Security Features
1. **Authentication**: All endpoints require valid JWT token
2. **Authorization**: User ID extracted from JWT, all queries scoped to authenticated user
3. **Input Validation**: 
   - Required fields checked before DB operations
   - Bounds sanitization on radius_km and days
   - Limit pagination to max 100 results
4. **SQL Injection Protection**: All queries use parameterized statements
5. **Soft Delete**: 30-day retention before permanent removal (optional)

## Database Performance
1. **Indexes**: Optimized for common queries (user dashboard, UUID lookup)
2. **Connection Pooling**: Reuses connections via `db_utils`
3. **JSONB Storage**: Flexible schema, supports GIN indexes if needed later
4. **Partial Indexes**: Only index active (non-deleted) itineraries

## Migration Instructions

### Option 1: Via Railway Shell (Recommended)
```bash
# In Railway dashboard, open shell for sentinel_ai_rss service
python apply_itinerary_migration.py
```

### Option 2: Via psql (Direct)
```bash
railway connect
\i migrations/004_travel_risk_itineraries.sql
```

### Option 3: Auto-apply on Deploy
Add to `main.py` startup (optional):
```python
# Apply migration on first run
try:
    from db_utils import execute
    with open('migrations/004_travel_risk_itineraries.sql') as f:
        execute(f.read())
except Exception as e:
    logger.warning(f"Migration may already be applied: {e}")
```

## Testing

### Syntax Check (Local)
```bash
python test_itinerary_syntax.py
```

### Manual API Testing
```bash
# Create itinerary
curl -X POST https://your-app.railway.app/api/travel-risk/itinerary \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Trip to Colombia",
    "data": {
      "waypoints": [{"lat": 4.6, "lon": -74.08, "name": "Bogotá"}],
      "routes": [],
      "risk_analysis": {"overall_risk": "medium"}
    }
  }'

# List itineraries
curl https://your-app.railway.app/api/travel-risk/itinerary?limit=10 \
  -H "Authorization: Bearer $TOKEN"

# Get specific itinerary
curl https://your-app.railway.app/api/travel-risk/itinerary/UUID \
  -H "Authorization: Bearer $TOKEN"
```

## Frontend Integration Example

```typescript
// types.ts
export interface Itinerary {
  id: number;
  itinerary_uuid: string;
  user_id: number;
  title: string | null;
  description: string | null;
  data: {
    waypoints: Array<{lat: number; lon: number; name: string}>;
    routes: any[];
    risk_analysis: any;
    metadata?: any;
  };
  created_at: string;
  updated_at: string;
  version: number;
}

// api.ts
export async function createItinerary(data: {
  title?: string;
  description?: string;
  data: any;
}): Promise<Itinerary> {
  const res = await fetch('/api/travel-risk/itinerary', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${getToken()}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });
  const json = await res.json();
  return json.itinerary;
}

export async function listItineraries(
  limit = 20,
  offset = 0
): Promise<Itinerary[]> {
  const res = await fetch(
    `/api/travel-risk/itinerary?limit=${limit}&offset=${offset}`,
    {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    }
  );
  const json = await res.json();
  return json.itineraries;
}
```

## Future Enhancements
1. **Sharing**: Add `share_token` for public itinerary links
2. **Templates**: Popular route templates (e.g., "Bogotá to Medellín")
3. **Collaboration**: Multi-user itineraries with permissions
4. **Analytics**: Track popular routes, risk trends
5. **Export**: PDF/Excel export of itineraries
6. **Notifications**: Alert users when risk levels change on saved routes
7. **GIN Index**: Add `CREATE INDEX idx_itinerary_data_gin ON travel_itineraries USING GIN (data);` for fast JSONB queries

## Deployment Checklist
- [x] Create migration SQL file
- [x] Create itinerary_manager utility module
- [x] Add 6 API endpoints to main.py
- [x] Add bounds sanitization to /api/travel-risk/assess
- [x] Test syntax locally
- [ ] Apply migration to Railway database
- [ ] Test endpoints in production
- [ ] Update frontend to use new endpoints
- [ ] Monitor logs for errors

## Files Modified/Created
1. **Created**: `migrations/004_travel_risk_itineraries.sql`
2. **Created**: `utils/itinerary_manager.py`
3. **Created**: `apply_itinerary_migration.py`
4. **Created**: `test_itinerary_syntax.py`
5. **Modified**: `main.py` (added 6 endpoints + bounds sanitization)

## Commit Message
```
feat: implement travel risk itinerary persistence

- Add travel_itineraries table with JSONB data storage
- Implement CRUD endpoints with JWT authentication
- Add bounds sanitization (radius 1-500km, days 1-365)
- Support soft delete with 30-day retention
- Add pagination and version tracking
- Optimize with indexes for user dashboard queries
```
