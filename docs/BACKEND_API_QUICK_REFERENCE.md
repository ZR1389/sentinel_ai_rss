# BACKEND API QUICK REFERENCE

## Authentication Flow

```
1. Register:    POST /auth/register     → { email, password }
2. Verify:      POST /auth/verify/send  → { email }
                POST /auth/verify/confirm → { email, code }
3. Login:       POST /auth/login        → { email, password }
4. Response:    { access_token, refresh_token, user }
5. Use:         Authorization: Bearer {access_token}
6. Refresh:     POST /auth/refresh      → { refresh_token }
```

## Travel Risk Assessment

### Single Location
```bash
POST /api/travel-risk/assess
{
  "lat": 40.7128,
  "lon": -74.0060,
  "destination": "New York",
  "country_code": "US",
  "radius_km": 50,
  "days": 14,
  "format": "structured"  # or "concise"
}

Response:
{
  "assessment": {
    "risk_level": "MODERATE",
    "threat_count": 8,
    "top_threats": [...],
    "location": { "lat": 40.7128, "lon": -74.0060 }
  },
  "advisory": "Tactical recommendations..."
}
```

### Create Itinerary
```bash
POST /api/travel-risk/itinerary
Header: Authorization: Bearer {token}
{
  "title": "NYC Trip",
  "data": {
    "destinations": [
      { "lat": 40.7128, "lon": -74.0060, "name": "NYC" }
    ],
    "settings": { ... }
  }
}

Response:
{
  "ok": true,
  "data": {
    "id": 123,
    "itinerary_uuid": "uuid-xxx",
    "version": 1,
    "created_at": "2025-12-06T...",
    "updated_at": "2025-12-06T..."
  }
}
Header: ETag: "itinerary/uuid-xxx/v1"
```

### List Itineraries
```bash
GET /api/travel-risk/itinerary?limit=10&offset=0
Header: Authorization: Bearer {token}

Response:
{
  "ok": true,
  "data": {
    "items": [...],
    "total": 25,
    "count": 10,
    "has_next": true,
    "next_offset": 10,
    "limit": 10,
    "offset": 0
  }
}
```

### Update Itinerary (Optimistic Locking)
```bash
PATCH /api/travel-risk/itinerary/{uuid}
Header: Authorization: Bearer {token}
Header: If-Match: "itinerary/uuid-xxx/v1"
{
  "title": "NYC Trip Updated",
  "data": { ... }
}

Response:
- 200 OK with updated data
- 412 Precondition Failed (version mismatch - stale)
```

### Delete Itinerary
```bash
DELETE /api/travel-risk/itinerary/{uuid}?permanent=false
Header: Authorization: Bearer {token}

Response:
{
  "ok": true,
  "data": { "deleted": true, "permanent": false }
}
```

### Get Itinerary Stats
```bash
GET /api/travel-risk/itinerary/stats
Header: Authorization: Bearer {token}

Response:
{
  "ok": true,
  "data": {
    "total_itineraries": 10,
    "active_itineraries": 8,
    "deleted": 2,
    "destinations_tracked": 45,
    "upcoming_trips_next_30d": 3,
    "last_updated": "2025-12-06T10:30:00Z"
  }
}
```

## Route Analysis

### Analyze Multiple Waypoints
```bash
POST /api/travel-risk/route-analysis
Header: Authorization: Bearer {token}
{
  "waypoints": [
    { "lat": 40.7128, "lon": -74.0060, "name": "NYC" },
    { "lat": 34.0522, "lon": -118.2437, "name": "LA" }
  ],
  "radius_km": 50,
  "days": 14
}

Response:
{
  "ok": true,
  "analysis": {
    "overall_risk": "HIGH",
    "waypoint_count": 2,
    "total_threats": 15,
    "waypoint_assessments": [
      {
        "waypoint_index": 0,
        "name": "NYC",
        "risk_level": "MODERATE",
        "threat_count": 8
      },
      ...
    ],
    "top_threats": [...],
    "risk_factors": ["..."],
    "recommendations": ["..."]
  }
}
```

### Analyze Corridor (Point-to-Point)
```bash
POST /api/travel-risk/route-corridor
Header: Authorization: Bearer {token}
{
  "point1": { "lat": 40.7128, "lon": -74.0060 },
  "point2": { "lat": 34.0522, "lon": -118.2437 },
  "radius_km": 50,
  "days": 14
}

Response:
{
  "ok": true,
  "corridor": {
    "overall_risk": "MODERATE",
    "corridor_distance_km": 3935.2,
    "segments_analyzed": 80,
    "total_threats": 42,
    "segment_assessments": [...],
    "top_threats": [...],
    "recommendations": [...]
  }
}
```

## Chat & Advisory

```bash
POST /chat
Header: Authorization: Bearer {token}
{
  "message": "What are the current threats in Syria?",
  "context": { "location": "Syria" }
}

Response:
{
  "ok": true,
  "advisory": "Tactical response with recommendations...",
  "model": "grok",
  "usage": { "tokens": 250 }
}
```

## Error Responses

```json
{
  "error": "Descriptive error message",
  "code": "ERROR_CODE",
  "status": 400
}
```

### Common Error Codes
| Code | Status | Meaning |
|------|--------|---------|
| `INVALID_PARAMS` | 400 | Missing required fields |
| `UNAUTHORIZED` | 401 | Missing or invalid token |
| `FORBIDDEN` | 403 | Plan doesn't include feature |
| `NOT_FOUND` | 404 | Resource doesn't exist |
| `PRECONDITION_FAILED` | 412 | ETag mismatch (stale update) |
| `RATE_LIMIT` | 429 | Too many requests |
| `SERVER_ERROR` | 500 | Backend error |

## Rate Limits

```
Auth endpoints:     5/min per IP
Chat:              10/day (FREE), 100/day (PRO), unlimited (BUSINESS)
Travel Risk:        5/day (FREE), unlimited (PRO+)
General API:        100/min per user
```

## Plans & Feature Access

### FREE Plan
- 5 travel risk assessments/day
- 10 chats/day
- Read-only access
- No exports
- No email notifications

### PRO Plan ($9.99/month)
- Unlimited travel risk assessments
- 100 chats/day
- Full CRUD on itineraries
- PDF exports
- Email notifications
- API access

### BUSINESS Plan (Custom)
- Everything in PRO +
- Route analysis (waypoint + corridor)
- Unlimited chats
- Webhooks
- Team management
- Custom integrations

## Status Codes Reference

```
200 OK               - Success
201 Created          - Resource created
204 No Content       - Success, no body
400 Bad Request      - Invalid input
401 Unauthorized     - Auth required
403 Forbidden        - Plan gate / permission denied
404 Not Found        - Resource doesn't exist
412 Precondition Failed - Optimistic lock conflict
429 Too Many Requests   - Rate limit exceeded
500 Server Error     - Backend error
503 Service Unavailable - Database/LLM unavailable
```

## Health Checks

```bash
GET /health         → Full system check
GET /health/quick   → Basic check (no DB)
GET /ping           → Instant response
```

## Notes for Frontend

1. **Always check plan gating:** Some endpoints return 403 if user plan doesn't include feature
2. **Use ETag for optimistic locking:** Always send If-Match header on PATCH
3. **Handle pagination:** Responses include `has_next` and `next_offset`
4. **Retry on 503:** Database might be temporarily unavailable
5. **Cache assessment results:** Identical queries cached for 24h (same lat/lon/radius/days)
6. **Use Bearer tokens:** Format: `Authorization: Bearer {access_token}`
7. **Refresh tokens before expiry:** Tokens expire in 24h

---

**Last Updated:** December 6, 2025
