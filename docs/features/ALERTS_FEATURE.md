# Geofenced Alerts (Business Tier)

This document outlines the backend implementation status and usage details for the Business/Enterprise geofenced alerts feature.

## Summary
Front-end now sends an `alerts_config` object in itinerary create/update payloads. Backend validates, sanitizes, and persists this configuration inside the itinerary `data` JSONB under `data.alerts_config` (only effective for BUSINESS / ENTERPRISE tiers).

## Request Shape
```
POST /api/travel-risk/itinerary
PATCH /api/travel-risk/itinerary/:uuid
{
  "title": "Trip to Istanbul",
  "description": "Conference + sightseeing",
  "data": { ... },
  "alerts_config": {
     "enabled": true,
     "channels": ["email", "sms"],
     "radius_km": 12,
     "geofences": [
        {"id": "hotel", "lat": 41.0082, "lon": 28.9784},
        {"id": "airport", "lat": 40.9826, "lon": 28.8146}
     ]
  }
}
```

## Validation Rules
- Non-Business tiers: config is force-disabled regardless of client values.
- `enabled`: must be true along with valid channels + geofences to remain enabled.
- `channels`: subset of `["email","sms"]`; duplicates removed; case-insensitive.
- `radius_km`: clamped to `1..50` (default 10 if omitted while enabled).
- `geofences`: max 25 entries; each must have `id`, valid lat (-90..90), lon (-180..180).
- If channels or geofences empty post-sanitize -> disabled.
- Disabled config is normalized to:
  ```json
  {"enabled": false, "channels": [], "radius_km": null, "geofences": []}
  ```

## Persistence
Stored inline in itinerary JSONB under `data.alerts_config`. No separate table yet.

## Migration 005
Adds tracking columns:
```
last_alert_sent_at TIMESTAMPTZ
alerts_sent_count INTEGER DEFAULT 0
```
These are returned in itinerary responses for future UI stats.

## Response Example (Create)
```
{
  "ok": true,
  "data": {
     "itinerary_uuid": "...",
     "version": 1,
     "data": {
        ...,
        "alerts_config": {
           "enabled": true,
           "channels": ["email"],
           "radius_km": 10,
           "geofences": [{"id":"hotel","lat":41.0082,"lon":28.9784}]
        }
     },
     "last_alert_sent_at": null,
     "alerts_sent_count": 0
  }
}
```

## Future Engine (Stubbed)
`alert_engine_stub.evaluate_threats(threats, itineraries)` returns candidate alert events after Haversine distance filtering. Missing pieces:
- Debounce storage (hash of itinerary_uuid + geofence_id + threat_id).
- Rate limiting (<=5 alerts/hour/itinerary).
- Notification dispatch (email/SMS integration).
- Optional alerts history endpoint.

## Planned Enhancements
| Feature | Phase |
|---------|-------|
| Debounce + hash store | 2 |
| Rate limiting enforcement | 2 |
| Alerts history endpoint | 2 |
| Separate alert revision log | 3 |
| Spatial index / reverse geofence index | 3 |

## Error Handling
Malformed `alerts_config` yields `VALIDATION_ERROR` (HTTP 400). Minor issues auto-sanitized.

## Security & Performance Notes
- Lat/Lon sanitized & bounded; max 25 geofences prevents large payload abuse.
- Tier gating prevents free users from enabling alerts (reduces compute).
- Engine will batch by threat ingestion rather than per itinerary to reduce complexity.

## Quick Test (Python)
```python
from alerts_config_utils import validate_alerts_config
cfg = validate_alerts_config({
  'enabled': True,
  'channels': ['Email','sms','sms'],
  'radius_km': 500,  # will clamp to 50
  'geofences': [{'id':'hotel','lat':41.0,'lon':28.9},{'id':'bad','lat':999,'lon':0}]
}, 'BUSINESS')
print(cfg)
```

## Rollout Status
Backend: COMPLETE (validation, persistence, migration file 005, stub engine)
Frontend: EXPECTS config; storing now.
Migration 005: Apply via `/admin/migration/apply` with body `{"migration":"005_geofenced_alerts.sql"}`.

---
For questions or extension planning, open a ticket with label `alerts-tier`.
