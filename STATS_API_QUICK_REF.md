# Stats API Quick Reference

## Endpoint
```
GET /api/stats/overview?days={7|30|90}
Authorization: Bearer <token>
```

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `ok` | boolean | Success status |
| `updated_at` | string | ISO timestamp |
| `threats_7d` | number | Alert count last 7 days |
| `threats_30d` | number | Alert count last 30 days |
| `trend_7d` | number | Percent change vs previous week |
| `active_monitors` | number | Active traveler profiles |
| `tracked_locations` | number | Distinct alert locations with coords |
| `chat_messages_month` | number | User's chat usage this month |
| `window_days` | number | Actual window used (7/30/90) |
| `max_window_days` | number | Plan limit (FREE=7, PRO=30, ENT=90) |
| `weekly_trends` | array | `[{date, count}]` - daily counts |
| `top_regions` | array | `[{region, count, percentage}]` - top 5 |
| `severity_breakdown` | object | See below |

## Severity Breakdown Object
```json
{
  "critical": 89,
  "high": 234,
  "medium": 567,
  "low": 353,
  "total": 1243,
  "critical_pct": 7.2,
  "high_pct": 18.8,
  "medium_pct": 45.6,
  "low_pct": 28.4
}
```

## Plan Limits

| Plan | Max Window | statistics_days |
|------|------------|-----------------|
| FREE | 7 days | 7 |
| PRO | 30 days | 30 |
| ENTERPRISE | 90 days | 90 |
| VIP | 90 days | 90 |

## Caching
- **TTL**: 120 seconds (2 minutes)
- **Key**: `stats:{email}:{window_days}`
- **Storage**: In-memory (`_STATS_OVERVIEW_CACHE`)

## HTTP Status Codes
- `200` - Success
- `401` - Unauthorized (missing/invalid token)
- `503` - Database unavailable
- `500` - Internal server error

## Example Request
```bash
curl -H "Authorization: Bearer eyJhbGci..." \
  "https://sentinelairss-production.up.railway.app/api/stats/overview?days=30"
```

## Example Response (Compact)
```json
{
  "ok": true,
  "updated_at": "2025-11-21T10:30:00Z",
  "threats_7d": 1243,
  "threats_30d": 4892,
  "trend_7d": 15,
  "active_monitors": 3,
  "tracked_locations": 87,
  "chat_messages_month": 45,
  "window_days": 30,
  "max_window_days": 30,
  "weekly_trends": [{...}, ...],
  "top_regions": [{...}, ...],
  "severity_breakdown": {...}
}
```

## Frontend Usage (React)
```tsx
const { data } = useQuery({
  queryKey: ['stats', 30],
  queryFn: () => fetch('/api/stats/overview?days=30', {
    headers: { 'Authorization': `Bearer ${token}` }
  }).then(r => r.json())
});
```

## TypeScript Type
```typescript
interface StatsOverview {
  ok: boolean;
  updated_at: string;
  threats_7d: number;
  threats_30d: number;
  trend_7d: number;
  active_monitors: number;
  tracked_locations: number;
  chat_messages_month: number;
  window_days: 7 | 30 | 90;
  max_window_days: 7 | 30 | 90;
  weekly_trends: Array<{ date: string; count: number }>;
  top_regions: Array<{ region: string; count: number; percentage: number }>;
  severity_breakdown: {
    critical: number; high: number; medium: number; low: number;
    total: number;
    critical_pct: number; high_pct: number; medium_pct: number; low_pct: number;
  };
}
```

## Key Changes vs Original Spec

| Feature | Original | Enhanced |
|---------|----------|----------|
| Window limits | None | Plan-based (7/30/90) |
| Severity data | Counts only | Counts + percentages + total |
| Tracked locations | User contexts | Distinct alert locations |
| Caching | Not specified | 2-minute TTL |
| Days param | 7\|30 | 7\|30\|90 |
| Response fields | Basic | +max_window_days, severity_pct |

## Test Commands
```bash
# Get token
TOKEN=$(curl -X POST .../auth/login -d '{"email":"...","password":"..."}' | jq -r .access_token)

# Test default window
curl -H "Authorization: Bearer $TOKEN" .../api/stats/overview

# Test 30-day window
curl -H "Authorization: Bearer $TOKEN" .../api/stats/overview?days=30

# Test with Python script
python test_stats_endpoint.py
```

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| 401 Unauthorized | Missing/invalid token | Check Authorization header |
| 503 Service Unavailable | DB connection failed | Check DATABASE_URL |
| Empty arrays | No alerts in DB | Seed database with test data |
| Window limited | Plan restriction | Upgrade plan or reduce days param |

## Notes

- **Auto-refresh**: Frontend should poll every 2-5 minutes
- **Plan upgrade**: Show locked features when `window_days < max_window_days`
- **Mobile**: All percentages work well in compact layouts
- **Export**: All fields suitable for CSV/PDF reports
- **Real-time**: Use caching + periodic refresh, not WebSocket

---

**See full documentation:**
- `STATS_API_SUMMARY.md` - Complete implementation guide
- `FRONTEND_STATS_INTEGRATION.md` - React/TypeScript examples
- `test_stats_endpoint.py` - Test utility
