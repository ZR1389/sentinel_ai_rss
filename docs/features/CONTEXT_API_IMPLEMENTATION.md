# User Context API Implementation

## Phase 1: Database Migration ✅

**File:** `migrate_user_context.sql`

### Schema
```sql
CREATE TABLE user_context (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    active_investigation JSONB,
    recent_queries JSONB DEFAULT '[]'::jsonb,
    saved_locations JSONB DEFAULT '[]'::jsonb,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Features
- Auto-updating `updated_at` timestamp via trigger
- Indexed on `user_id` for fast lookups
- Cascading delete when user is removed
- Comprehensive column documentation

### Deploy Migration
```bash
psql $DATABASE_URL -f migrate_user_context.sql
```

---

## Phase 2: Backend API Endpoints ✅

**File:** `main.py` (added 3 new endpoints)

### 1. GET `/api/context`
**Purpose:** Retrieve user's current context across all products

**Authentication:** Required (`@login_required`)

**Response:**
```json
{
  "ok": true,
  "investigation": {
    "topic": "ransomware attacks",
    "started_at": "2025-11-20T10:30:00Z"
  },
  "recent": [
    {
      "query": "Ukraine cyber attacks",
      "timestamp": "2025-11-21T14:22:00Z"
    }
  ],
  "locations": [
    {
      "name": "Kyiv, Ukraine",
      "lat": 50.4501,
      "lon": 30.5234,
      "saved_at": "2025-11-20T12:00:00Z"
    }
  ]
}
```

**Usage:**
- **Sentinel AI Chat:** Resume active investigations
- **Threat Map:** Load recent search locations
- **Travel Risk Map:** Show saved travel destinations

---

### 2. POST `/api/context`
**Purpose:** Update user context (investigation, query, location, clear)

**Authentication:** Required (`@login_required`)

**Request Body:**
```json
{
  "type": "investigation|query|location|clear",
  "data": { /* context-specific payload */ }
}
```

#### Type: `investigation`
Set active investigation for Sentinel AI Chat:
```json
{
  "type": "investigation",
  "data": {
    "topic": "ransomware trends",
    "focus": "healthcare sector",
    "started_at": "2025-11-21T10:00:00Z"
  }
}
```

#### Type: `query`
Add to recent queries (keeps last 10):
```json
{
  "type": "query",
  "data": {
    "query": "Russian cyberattacks",
    "timestamp": "2025-11-21T14:30:00Z",
    "product": "threat_map"
  }
}
```

#### Type: `location`
Save location to user's list (deduplicates automatically):
```json
{
  "type": "location",
  "data": {
    "name": "London, UK",
    "lat": 51.5074,
    "lon": -0.1278,
    "saved_at": "2025-11-21T15:00:00Z",
    "product": "travel_risk_map"
  }
}
```

#### Type: `clear`
Clear active investigation:
```json
{
  "type": "clear",
  "data": {}
}
```

**Response:**
```json
{
  "ok": true,
  "message": "Context updated"
}
```

---

### 3. GET `/api/context/search?q={query}`
**Purpose:** Unified location search for Threat Map and Travel Risk Map

**Authentication:** Required (`@login_required`)

**Parameters:**
- `q` (string, min 3 chars): Search query

**Response:**
```json
{
  "ok": true,
  "locations": [
    {
      "location": "Kyiv",
      "count": 156,
      "lat": 50.4501,
      "lon": 30.5234,
      "zoom": 12
    }
  ],
  "travel": {
    "label": "Kyiv",
    "lat": 50.4501,
    "lon": 30.5234
  }
}
```

**Features:**
- Searches across `city`, `country`, and `title` fields in alerts
- Returns top 5 locations by alert count
- Provides `travel` object for immediate risk assessment
- Only returns locations with valid coordinates

---

## Integration with Three Products

### 1. Sentinel AI Chat
**Use Cases:**
- Resume active investigations on page reload
- Store conversation context across sessions
- Track investigation topics and focus areas

**API Calls:**
```javascript
// Load active investigation
GET /api/context

// Save new investigation
POST /api/context
{
  "type": "investigation",
  "data": { "topic": "...", "started_at": "..." }
}

// Clear when investigation complete
POST /api/context
{
  "type": "clear",
  "data": {}
}
```

---

### 2. Threat Map
**Use Cases:**
- Remember recent location searches
- Quick access to frequently viewed areas
- Track search history across sessions

**API Calls:**
```javascript
// Load recent searches
GET /api/context

// Search for location
GET /api/context/search?q=ukraine

// Save search query
POST /api/context
{
  "type": "query",
  "data": { "query": "ukraine", "timestamp": "...", "product": "threat_map" }
}

// Save frequently viewed location
POST /api/context
{
  "type": "location",
  "data": { "name": "Kyiv", "lat": 50.45, "lon": 30.52, ... }
}
```

---

### 3. Travel Risk Map
**Use Cases:**
- Save planned travel destinations
- Quick risk assessment for saved locations
- Track travel history and risk trends

**API Calls:**
```javascript
// Load saved travel destinations
GET /api/context

// Search for travel destination
GET /api/context/search?q=paris

// Save travel location
POST /api/context
{
  "type": "location",
  "data": { "name": "Paris", "lat": 48.85, "lon": 2.35, "product": "travel_risk_map" }
}
```

---

## Security Features

✅ **JWT Authentication:** All endpoints require valid access token  
✅ **User Isolation:** Context is scoped to authenticated user via `user_id`  
✅ **Input Validation:** Type checking and length limits on queries  
✅ **CORS Support:** OPTIONS preflight handling for all endpoints  
✅ **Rate Limiting:** Inherits from global Flask-Limiter configuration  
✅ **SQL Injection Prevention:** Parameterized queries throughout  

---

## Database Performance

### Indexes
- Primary key index on `user_id` (automatic)
- Custom index: `idx_user_context_user_id`

### Optimizations
- JSONB array operations use PostgreSQL native functions
- Query history limited to 10 most recent (prevents bloat)
- Location deduplication via JSONB containment check (`@>`)
- Auto-vacuum enabled via timestamp trigger

---

## Testing

### 1. Test Database Migration
```bash
# Apply migration
psql $DATABASE_URL -f migrate_user_context.sql

# Verify table exists
psql $DATABASE_URL -c "SELECT * FROM user_context LIMIT 1;"
```

### 2. Test API Endpoints
```bash
# Get access token first
ACCESS_TOKEN="your_jwt_token"

# Get context
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  https://sentinelairss-production.up.railway.app/api/context

# Save investigation
curl -X POST \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type":"investigation","data":{"topic":"test"}}' \
  https://sentinelairss-production.up.railway.app/api/context

# Search locations
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://sentinelairss-production.up.railway.app/api/context/search?q=ukraine"
```

---

## Next Steps

### Frontend Integration
1. **Create React hooks:**
   - `useUserContext()` - Get/set context
   - `useLocationSearch()` - Search locations
   - `useInvestigation()` - Manage investigations

2. **TypeScript types:**
   ```typescript
   interface UserContext {
     investigation: Investigation | null;
     recent: Query[];
     locations: SavedLocation[];
   }
   
   interface Investigation {
     topic: string;
     focus?: string;
     started_at: string;
   }
   ```

3. **Context provider:**
   - Wrap apps with `<ContextProvider>`
   - Share state across Sentinel AI Chat, Threat Map, Travel Risk Map

### Monitoring
- Add metrics for context API usage
- Track search query patterns
- Monitor saved location trends

---

## API Summary

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/context` | GET | ✅ | Get user context |
| `/api/context` | POST | ✅ | Update context |
| `/api/context/search` | GET | ✅ | Search locations |

**Base URL:** `https://sentinelairss-production.up.railway.app`
