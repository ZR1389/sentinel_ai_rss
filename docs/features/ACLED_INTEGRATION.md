# ACLED Integration Guide

## Overview

ACLED (Armed Conflict Location & Event Data Project) is integrated as a third intelligence source in Sentinel AI, alongside RSS feeds and SOCMINT data. ACLED provides real-time conflict and violence event data from around the world.

## System Architecture

### Data Flow

```
┌─────────────────┐
│  RSS Processor  │───┐
└─────────────────┘   │
                      ├──→ raw_alerts table
┌─────────────────┐   │
│ ACLED Collector │───┘
└─────────────────┘
                      
        │
        ↓
        
┌─────────────────────┐      ┌──────────────────┐
│   Threat Engine     │←─────│ socmint_profiles │
└─────────────────────┘      └──────────────────┘
        │                            ↑
        │                            │
        ↓                     ┌──────────────┐
                             │ SOCMINT      │
   alerts table              │ Service      │
        │                    └──────────────┘
        ↓
        
┌─────────────────┐
│     Advisor     │
│  (User-Facing)  │
└─────────────────┘
```

### Table Structure

**raw_alerts** (Primary Intelligence Sources)
- Sources: RSS feeds, ACLED API
- Purpose: Raw, unprocessed threat events
- Fields: uuid, title, summary, source, published, latitude, longitude, country, tags

**socmint_profiles** (Enrichment Layer)
- Sources: Instagram scraper, Facebook scraper
- Purpose: Social media profile data for scoring augmentation
- Fields: platform, identifier, profile_data, posts_data, scraped_timestamp

**alerts** (Enriched Output)
- Source: Threat Engine processing
- Purpose: Scored and enriched alerts for end users
- Includes: Base threat scores + SOCMINT augmentation scores

## ACLED Collector Implementation

### File: `acled_collector.py`

**Key Functions:**

1. **`get_acled_token()`**
   - OAuth2 authentication flow
   - Exchanges email/password for Bearer token
   - Returns: access_token (valid for API requests)

2. **`fetch_acled_events(countries, days_back, token)`**
   - Fetches conflict events from ACLED API
   - Parameters:
     - `countries`: List of country names (e.g., ["Nigeria", "Kenya"])
     - `days_back`: Number of days to look back (e.g., 1, 7, 30)
     - `token`: Bearer token from authentication
   - Returns: List of event dictionaries with conflict data

3. **`write_acled_to_raw_alerts(events)`**
   - Writes events to `raw_alerts` table
   - Uses `ON CONFLICT DO NOTHING` to prevent duplicates
   - Tags events with `source_kind='acled'` and `source_tag='conflict_data'`
   - Returns: Count of inserted events

4. **`run_acled_collector(countries=None, days_back=None)`**
   - Main orchestrator function
   - Uses config defaults if parameters not provided
   - Returns: Dict with `events_fetched`, `events_inserted`, `duration_seconds`

### Configuration

**Environment Variables (.env):**
```bash
ACLED_EMAIL=your_email@example.com
ACLED_PASSWORD=your_password
ACLED_ENABLED=true
ACLED_DEFAULT_COUNTRIES=Nigeria,Kenya,Sudan,Serbia,Ukraine,Haiti,Somalia,Iraq,Israel,Burkina Faso,Mali,Niger,Afghanistan,Iran,Lebanon,Libya,Chad
ACLED_DAYS_BACK=1
```

**Config Object (config.py):**
```python
@dataclass
class ACLEDConfig:
    email: str
    password: str
    enabled: bool
    default_countries: List[str]
    days_back: int
    timeout: int
```

## Admin Endpoint

### Manual Trigger

**Endpoint:** `POST /admin/acled/run`

**Authentication:** Requires `ADMIN_API_KEY` header or query parameter

**Parameters:**
- `countries` (optional): Comma-separated country list (overrides config defaults)
- `days_back` (optional): Number of days to fetch (overrides config default)

**Example Request:**
```bash
curl -X POST "https://your-app.railway.app/admin/acled/run?countries=Nigeria,Kenya&days_back=7" \
  -H "X-API-Key: your_admin_api_key"
```

**Response:**
```json
{
  "status": "success",
  "events_fetched": 145,
  "events_inserted": 142,
  "duration_seconds": 3.45
}
```

## Automated Collection

### Railway Cron Job

**Schedule:** Daily at 6:00 AM UTC

**Cron Expression:** `0 6 * * *`

**Command:** `python acled_collector.py`

**Railway Configuration:**
- Schedule: `0 6 * * *`
- Command: `python acled_collector.py`
- No need to repeat environment variables (inherits from project)

## Frontend Integration

### Understanding the Data

When you open your frontend with threat alerts and maps, ACLED events are already integrated into the same `alerts` table as RSS-sourced threats. You don't need separate handling for ACLED vs RSS alerts.

### API Endpoints to Use

**1. Get All Alerts (Including ACLED)**
```javascript
// Fetch alerts from Advisor endpoint
fetch('/api/alerts', {
  headers: {
    'Authorization': 'Bearer ' + userToken
  }
})
.then(response => response.json())
.then(alerts => {
  // alerts array contains threats from all sources:
  // - RSS feeds (source_kind='rss')
  // - ACLED data (source_kind='acled')
  
  alerts.forEach(alert => {
    if (alert.source_kind === 'acled') {
      // This is a conflict event from ACLED
      // Display with conflict-specific styling
    }
  });
});
```

**2. Filter Alerts by Source**
```javascript
// If you want to show only ACLED alerts
const acledAlerts = alerts.filter(a => a.source_kind === 'acled');

// If you want to show only RSS alerts
const rssAlerts = alerts.filter(a => a.source_kind === 'rss');
```

### Map Visualization

ACLED events include geographic coordinates that can be displayed on your map:

```javascript
// Example: Adding ACLED events to a map
alerts.forEach(alert => {
  if (alert.latitude && alert.longitude) {
    const markerColor = alert.source_kind === 'acled' 
      ? '#FF4444'  // Red for conflict events
      : '#4444FF'; // Blue for RSS threats
    
    addMarker({
      lat: alert.latitude,
      lng: alert.longitude,
      title: alert.title,
      description: alert.summary,
      color: markerColor,
      source: alert.source_kind,
      threatScore: alert.threat_score,
      socmintScore: alert.socmint_best // Social media augmentation
    });
  }
});
```

### Alert Card Styling

Differentiate ACLED alerts visually:

```javascript
function renderAlertCard(alert) {
  const sourceLabel = {
    'acled': '🔴 Conflict Event',
    'rss': '📰 News Alert'
  }[alert.source_kind] || '📋 Alert';
  
  return `
    <div class="alert-card ${alert.source_kind}">
      <span class="source-badge">${sourceLabel}</span>
      <h3>${alert.title}</h3>
      <p>${alert.summary}</p>
      <div class="metadata">
        <span>📍 ${alert.country || 'Unknown'}</span>
        <span>⚠️ Score: ${alert.threat_score}/100</span>
        ${alert.socmint_best ? 
          `<span>👥 Social: ${alert.socmint_best}/100</span>` : ''}
        <span>🕒 ${new Date(alert.published).toLocaleDateString()}</span>
      </div>
    </div>
  `;
}
```

### Real-Time Updates

If you have WebSocket support for live alerts:

```javascript
// Listen for new alerts (including ACLED)
socket.on('new_alert', (alert) => {
  if (alert.source_kind === 'acled') {
    // Show notification for conflict event
    showNotification({
      title: '🔴 New Conflict Event',
      body: alert.title,
      urgency: 'high'
    });
    
    // Add to map immediately
    addMarkerToMap(alert);
  }
});
```

### Filtering UI

Add source filter to your frontend:

```html
<div class="filter-controls">
  <label>
    <input type="checkbox" id="show-rss" checked>
    📰 News Alerts
  </label>
  <label>
    <input type="checkbox" id="show-acled" checked>
    🔴 Conflict Events
  </label>
  <label>
    <input type="checkbox" id="show-socmint-enriched">
    👥 Social Media Verified
  </label>
</div>
```

```javascript
// Filter logic
function applyFilters() {
  const showRSS = document.getElementById('show-rss').checked;
  const showACLED = document.getElementById('show-acled').checked;
  const showSocmint = document.getElementById('show-socmint-enriched').checked;
  
  const filteredAlerts = alerts.filter(alert => {
    if (!showRSS && alert.source_kind === 'rss') return false;
    if (!showACLED && alert.source_kind === 'acled') return false;
    if (showSocmint && !alert.socmint_best) return false;
    return true;
  });
  
  updateMapMarkers(filteredAlerts);
  updateAlertList(filteredAlerts);
}
```

### Country-Specific Views

Since ACLED data is country-tagged, you can create country-specific dashboards:

```javascript
// Example: Nigeria conflict dashboard
fetch('/api/alerts?country=Nigeria&source_kind=acled')
  .then(response => response.json())
  .then(alerts => {
    renderCountryDashboard('Nigeria', alerts);
  });
```

### Timeline View

Display ACLED events chronologically:

```javascript
function createTimeline(alerts) {
  const acledEvents = alerts
    .filter(a => a.source_kind === 'acled')
    .sort((a, b) => new Date(b.published) - new Date(a.published));
  
  return acledEvents.map(event => ({
    date: event.published,
    title: event.title,
    location: `${event.city || ''}, ${event.country || ''}`.trim(),
    severity: event.threat_score,
    tags: event.tags
  }));
}
```

## Key Points for Frontend Development

1. **Unified Data**: ACLED alerts appear in the same `alerts` table as RSS feeds
2. **Source Identification**: Use `source_kind='acled'` to identify conflict events
3. **Geographic Data**: ACLED events always include coordinates (latitude/longitude)
4. **Threat Scoring**: All alerts have `threat_score` (base) and optionally `socmint_best` (social media augmentation)
5. **No Separate API**: No need for separate ACLED endpoint - use existing `/api/alerts`
6. **Real-Time**: ACLED data refreshes daily at 6 AM UTC via cron job
7. **Manual Refresh**: Admins can trigger immediate collection via `/admin/acled/run`

## Troubleshooting

### ACLED API Access Issues

If you see 403 Forbidden errors:
1. Verify ACLED account has API access enabled
2. Contact access@acleddata.com to confirm API tier
3. Test with historical dates (days_back=7) instead of current date

### No ACLED Alerts Appearing

1. Check cron job logs in Railway dashboard
2. Verify `ACLED_ENABLED=true` in environment variables
3. Test manual collection: `POST /admin/acled/run`
4. Check database: `SELECT COUNT(*) FROM raw_alerts WHERE source_kind='acled'`

### Duplicate Events

The collector uses `ON CONFLICT DO NOTHING` based on event ID, so duplicates should not occur. If you see duplicates, check the ACLED event_id_cnty field mapping.

## Future Enhancements

- **Additional Countries**: Expand `ACLED_DEFAULT_COUNTRIES` in .env
- **Event Type Filtering**: Filter by ACLED event types (battles, protests, riots, etc.)
- **Historical Backfill**: Run with `days_back=365` to load historical conflict data
- **Alert Severity Mapping**: Map ACLED fatality counts to threat scores
- **Cross-Source Correlation**: Link ACLED events with related RSS articles via location/time proximity

## References

- ACLED API Documentation: https://acleddata.com/api-documentation/acled-endpoint/
- ACLED Codebook: https://acleddata.com/resources/general-guides/
- OAuth2 Flow: https://acleddata.com/api-documentation/authentication/
