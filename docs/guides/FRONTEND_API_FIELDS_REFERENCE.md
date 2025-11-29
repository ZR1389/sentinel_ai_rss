# Frontend API Fields Reference

## Critical Field Corrections

Your suspicions are **CORRECT**. Your current frontend code references fields that don't match the backend schema.

## ❌ INCORRECT Frontend Fields (Current)
```javascript
// WRONG - These fields DO NOT exist in the backend
alert.threat_level  // ❌ Wrong name
alert.score        // ❌ Wrong name (this exists but is legacy)
```

## ✅ CORRECT Backend Fields (Actual)

### Data Flow: raw_alerts → alerts Table

```
┌──────────────┐
│ raw_alerts   │ ← ACLED + RSS write here
│ (source)     │
└──────┬───────┘
       │
       ↓ Threat Engine enriches
       │
┌──────┴───────┐
│ alerts       │ ← Your frontend reads from here
│ (enriched)   │
└──────────────┘
```

### raw_alerts Table Fields (ACLED/RSS Input)

**Source Identification:**
- `source_kind` - Values: `"intelligence"` (ACLED), `"rss"` (RSS feeds)
- `source_tag` - Additional tagging (e.g., `"country:Nigeria"`, `"feed:bbc"`)
- `source_priority` - Optional priority level
- `source` - Human-readable source name (e.g., `"acled"`, `"BBC News"`)

**Content:**
- `uuid` - Unique identifier (format: `"acled:123"` or standard UUID)
- `title` - Alert title
- `summary` - Full description
- `published` - Event timestamp
- `latitude` / `longitude` - Coordinates
- `country`, `region`, `city` - Location data
- `tags` - JSONB array with metadata

### alerts Table Fields (Enriched Output - What Frontend Gets)

**⚠️ NOTE: The `alerts` table does NOT have `source_kind` or `source_tag` columns!**

These fields exist only in `raw_alerts`. Once enriched to the `alerts` table, you identify source by:
- `source` field (string like "acled", "BBC News", etc.)
- Or by checking the `uuid` prefix (e.g., starts with "acled:")

**Actual Fields Available in `/api/alerts` and `/alerts/latest` endpoints:**

#### Core Identification
```javascript
alert.uuid          // Unique identifier
alert.title         // Alert title
alert.summary       // Original description
alert.gpt_summary   // LLM-generated summary
alert.en_snippet    // English snippet (if translated)
alert.link          // Source URL
alert.source        // Source name (e.g., "acled", "BBC News")
```

#### Location
```javascript
alert.region        // Region/state
alert.country       // Country name
alert.city          // City name
alert.latitude      // Decimal latitude
alert.longitude     // Decimal longitude
alert.location_method        // How location was determined
alert.location_confidence    // "high", "medium", "low"
alert.location_sharing       // Boolean for privacy
```

#### Timing
```javascript
alert.published     // Event date/time
alert.ingested_at   // When added to system
```

#### Threat Classification
```javascript
alert.category              // Threat category (e.g., "Civil Unrest")
alert.subcategory          // Specific threat type
alert.category_confidence  // Confidence in categorization (0-1)
alert.threat_level         // ⚠️ EXISTS but may be null/empty
alert.threat_label         // Human-readable label
alert.domains              // JSONB array of affected domains
```

#### ⭐ SCORING FIELDS (Critical for Your Update)
```javascript
// PRIMARY SCORE FIELD
alert.score                 // 0-100 base threat score (legacy name, still used)

// CONFIDENCE
alert.confidence            // 0-1 overall confidence
alert.overall_confidence    // Alternative confidence field

// THREAT SCORE COMPONENTS (JSONB - contains SOCMINT breakdown)
alert.threat_score_components  // Object with detailed scoring
// Structure:
{
  "socmint_raw": 15.0,        // Raw SOCMINT score (0-100)
  "socmint_weighted": 4.5,    // SOCMINT contribution (30% weight)
  "socmint_weight": 0.3,      // Weight factor
  // ... other scoring components
}
```

**⚠️ IMPORTANT:** The field is called `score`, NOT `threat_score` in the SELECT queries, even though internally the threat engine uses `threat_score`. The database column and API response use `score`.

#### Trend & Risk
```javascript
alert.trend_direction        // "rising", "stable", "falling"
alert.trend_score           // Numeric trend score
alert.trend_score_msg       // Explanation
alert.anomaly_flag          // Boolean - is this anomalous?
alert.is_anomaly            // Alternative anomaly field
alert.future_risk_probability  // 0-1 probability of escalation
```

#### Analytics
```javascript
alert.sentiment             // Sentiment analysis
alert.forecast              // Risk forecast
alert.reasoning             // Why this score
alert.tags                  // Array of tag strings
alert.early_warning_indicators  // Array of warning signs
```

#### Metadata
```javascript
alert.model_used            // Which LLM processed this
alert.cluster_id            // Related alerts cluster
alert.incident_count_30d    // Historical context
alert.recent_count_7d       // Recent similar events
alert.baseline_avg_7d       // Average for comparison
alert.baseline_ratio        // Current vs baseline
```

## How to Identify ACLED vs RSS Alerts

Since `source_kind` is NOT in the `alerts` table, use these methods:

### Method 1: Check UUID prefix
```javascript
function isACLEDAlert(alert) {
  return alert.uuid && alert.uuid.startsWith('acled:');
}

function isRSSAlert(alert) {
  return alert.uuid && !alert.uuid.startsWith('acled:');
}
```

### Method 2: Check source field
```javascript
function isACLEDAlert(alert) {
  return alert.source === 'acled';
}
```

### Method 3: Add to threat_engine.py (Enhancement)
If you want `source_kind` in the `alerts` table, you need to:

1. **Add column to alerts table:**
```sql
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS source_kind TEXT;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS source_tag TEXT;
```

2. **Update threat_engine.py to preserve these fields:**
```python
# In enrich_single_alert() function, preserve source metadata
alert['source_kind'] = alert.get('source_kind')  # Pass through from raw_alerts
alert['source_tag'] = alert.get('source_tag')    # Pass through from raw_alerts
```

3. **Update db_utils.py save_alerts_to_db() to include them:**
Add `source_kind` and `source_tag` to the columns list and row coercion.

## Frontend Code Examples

### Correct Field Access

```javascript
// ✅ CORRECT - Accessing actual fields
function displayAlert(alert) {
  const score = alert.score;  // Not alert.threat_score
  const confidence = alert.confidence;
  const source = alert.source;
  const isACLED = alert.uuid.startsWith('acled:');
  
  // Get SOCMINT scoring breakdown
  const components = alert.threat_score_components || {};
  const socmintScore = components.socmint_raw || 0;
  const socmintContribution = components.socmint_weighted || 0;
  
  return {
    title: alert.title,
    score: score,
    confidence: (confidence * 100).toFixed(0) + '%',
    source: isACLED ? '🔴 ACLED Conflict' : '📰 ' + source,
    socmint: socmintScore > 0 ? `+${socmintContribution} from SOCMINT` : null,
    location: `${alert.city || ''}, ${alert.country || ''}`.trim()
  };
}
```

### Display Scoring with SOCMINT

```javascript
function renderScoringBreakdown(alert) {
  const baseScore = alert.score || 0;
  const components = alert.threat_score_components || {};
  
  const socmintRaw = components.socmint_raw || 0;
  const socmintWeighted = components.socmint_weighted || 0;
  const socmintWeight = components.socmint_weight || 0.3;
  
  // Calculate what the base score was before SOCMINT
  const scoreBeforeSOCMINT = baseScore - socmintWeighted;
  
  return `
    <div class="score-breakdown">
      <div class="base-score">
        <span>Base Threat Score:</span>
        <strong>${scoreBeforeSOCMINT.toFixed(1)}/100</strong>
      </div>
      
      ${socmintRaw > 0 ? `
        <div class="socmint-score">
          <span>👥 Social Media Intel:</span>
          <strong>${socmintRaw.toFixed(1)}/100</strong>
          <small>(${(socmintWeight * 100)}% weight = +${socmintWeighted.toFixed(1)})</small>
        </div>
      ` : ''}
      
      <div class="final-score">
        <span>Final Score:</span>
        <strong class="score-${getScoreSeverity(baseScore)}">
          ${baseScore.toFixed(1)}/100
        </strong>
      </div>
      
      <div class="confidence">
        <span>Confidence:</span>
        <strong>${((alert.confidence || 0) * 100).toFixed(0)}%</strong>
      </div>
    </div>
  `;
}

function getScoreSeverity(score) {
  if (score >= 80) return 'critical';
  if (score >= 60) return 'high';
  if (score >= 40) return 'medium';
  return 'low';
}
```

### Filter by Source Type

```javascript
// Filter controls
const filters = {
  showACLED: true,
  showRSS: true,
  showSOCMINTEnriched: false,
  minScore: 0
};

function filterAlerts(alerts, filters) {
  return alerts.filter(alert => {
    // Source type filter
    const isACLED = alert.uuid.startsWith('acled:');
    if (isACLED && !filters.showACLED) return false;
    if (!isACLED && !filters.showRSS) return false;
    
    // SOCMINT enrichment filter
    const hasSocmint = alert.threat_score_components?.socmint_raw > 0;
    if (filters.showSOCMINTEnriched && !hasSocmint) return false;
    
    // Score threshold
    if ((alert.score || 0) < filters.minScore) return false;
    
    return true;
  });
}
```

### Map Markers with Source Styling

```javascript
function addAlertToMap(alert, map) {
  if (!alert.latitude || !alert.longitude) return;
  
  const isACLED = alert.uuid.startsWith('acled:');
  const hasSocmint = alert.threat_score_components?.socmint_raw > 0;
  
  const marker = L.marker([alert.latitude, alert.longitude], {
    icon: getMarkerIcon(isACLED, alert.score, hasSocmint)
  });
  
  const popupContent = `
    <div class="alert-popup">
      <div class="source-badge ${isACLED ? 'acled' : 'rss'}">
        ${isACLED ? '🔴 ACLED' : '📰 News'}
      </div>
      <h4>${alert.title}</h4>
      <p>${alert.gpt_summary || alert.summary.substring(0, 150)}...</p>
      <div class="metadata">
        <span class="score" data-severity="${getScoreSeverity(alert.score)}">
          ⚠️ ${alert.score}/100
        </span>
        ${hasSocmint ? `
          <span class="socmint-badge">
            👥 +${alert.threat_score_components.socmint_weighted.toFixed(1)} SOCMINT
          </span>
        ` : ''}
        <span class="time">🕒 ${formatRelativeTime(alert.published)}</span>
      </div>
    </div>
  `;
  
  marker.bindPopup(popupContent);
  marker.addTo(map);
  
  return marker;
}

function getMarkerIcon(isACLED, score, hasSocmint) {
  const color = isACLED ? '#dc2626' : '#2563eb';  // red for ACLED, blue for RSS
  const size = hasSocmint ? 'large' : 'normal';
  const severity = getScoreSeverity(score);
  
  return L.divIcon({
    className: `custom-marker ${severity} ${size}`,
    html: `
      <div class="marker-inner" style="background-color: ${color};">
        ${isACLED ? '🔴' : '📰'}
        ${hasSocmint ? '<span class="socmint-indicator">👥</span>' : ''}
      </div>
    `
  });
}
```

## API Endpoint Test

Test your backend to verify field names:

```bash
# Get recent alerts and inspect response
curl -X GET "http://localhost:8080/alerts/latest?limit=5" \
  -H "Authorization: Bearer YOUR_TOKEN" | jq '.'

# Check specific alert scoring
curl -X GET "http://localhost:8080/alerts/ALERT_UUID/scoring" \
  -H "Authorization: Bearer YOUR_TOKEN" | jq '.threat_score_components'
```

## Summary of Changes Needed

### Your Frontend Needs to Update:

1. **Change `alert.threat_level` to `alert.threat_level`** (may be null) or use `alert.score` for numeric value
2. **Use `alert.score`** not `alert.threat_score` (that's internal name)
3. **Check `alert.uuid.startsWith('acled:')` to identify ACLED alerts** (not `source_kind`)
4. **Access SOCMINT via `alert.threat_score_components.socmint_raw`** (not a top-level field)
5. **Use `alert.confidence`** for overall confidence (0-1 scale, multiply by 100 for percentage)

### Example Migration:

```javascript
// ❌ OLD (WRONG)
const threatLevel = alert.threat_level;  // May not exist
const score = alert.score;               // This one is OK
const sourceKind = alert.source_kind;    // Doesn't exist in alerts table
const socmintScore = alert.socmint_best; // Doesn't exist

// ✅ NEW (CORRECT)
const threatLabel = alert.threat_label || 'Unknown';
const score = alert.score;  // Still works
const isACLED = alert.uuid.startsWith('acled:');
const socmintScore = alert.threat_score_components?.socmint_raw || 0;
const confidence = (alert.confidence * 100).toFixed(0) + '%';
```

## Need to Add source_kind to alerts?

If you want `source_kind` available directly in the `alerts` table (recommended for cleaner frontend code):

1. Run migration:
```sql
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS source_kind TEXT;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS source_tag TEXT;
CREATE INDEX IF NOT EXISTS idx_alerts_source_kind ON alerts(source_kind);
```

2. Update `threat_engine.py` in `enrich_single_alert()`:
```python
# Preserve source metadata from raw_alerts
alert['source_kind'] = alert.get('source_kind', 'rss')
alert['source_tag'] = alert.get('source_tag', '')
```

3. Update `db_utils.py` in `save_alerts_to_db()`:
Add to columns list and _coerce_row function.

4. Then frontend can use:
```javascript
if (alert.source_kind === 'intelligence') {
  // This is ACLED
} else if (alert.source_kind === 'rss') {
  // This is RSS
}
```
