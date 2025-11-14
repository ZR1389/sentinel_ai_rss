# SOCMINT Threat Score Components - API Exposure

## Overview
The threat scoring system now exposes detailed breakdowns showing how SOCMINT (Social Media Intelligence) and other factors contribute to the final threat score. This provides transparency and enables better threat assessment decisions.

## What's Exposed

### `threat_score_components` Field
All alert endpoints now include a `threat_score_components` JSONB field containing:

```json
{
  "socmint_raw": 15.0,
  "socmint_weighted": 4.5,
  "socmint_weight": 0.3,
  "base_score": 60.0,
  "final_score": 64.5
}
```

**Field Descriptions:**
- `socmint_raw`: Raw SOCMINT score (0-100) before weighting
- `socmint_weighted`: Actual contribution to final score (raw × weight)
- `socmint_weight`: Weight applied to SOCMINT (default: 0.3 = 30%)
- `base_score`: Threat score before SOCMINT augmentation
- `final_score`: Final threat score (base + socmint_weighted)

## API Endpoints

### 1. Get All Alerts with Components
```http
GET /alerts?limit=100
Authorization: Bearer <token>
```

**Response:**
```json
{
  "alerts": [
    {
      "uuid": "abc-123",
      "title": "Ransomware actor posts new leak",
      "score": 64.5,
      "threat_level": "HIGH",
      "confidence": 0.85,
      "threat_score_components": {
        "socmint_raw": 15.0,
        "socmint_weighted": 4.5,
        "socmint_weight": 0.3,
        "base_score": 60.0,
        "final_score": 64.5
      },
      ...
    }
  ]
}
```

### 2. Get Latest Alerts with Components
```http
GET /alerts/latest?limit=20&region=Europe
Authorization: Bearer <token>
```

**Response:**
```json
{
  "ok": true,
  "items": [
    {
      "uuid": "def-456",
      "score": 72.0,
      "threat_score_components": { ... },
      ...
    }
  ]
}
```

### 3. Get Detailed Scoring Breakdown (NEW)
```http
GET /alerts/<alert_uuid>/scoring
Authorization: Bearer <token>
```

**Example:**
```http
GET /alerts/abc-123/scoring
```

**Response:**
```json
{
  "ok": true,
  "alert": {
    "uuid": "abc-123",
    "title": "Ransomware actor posts new leak",
    "score": 64.5,
    "threat_level": "HIGH",
    "threat_label": "Critical Infrastructure",
    "confidence": 0.85,
    "threat_score_components": {
      "socmint_raw": 15.0,
      "socmint_weighted": 4.5,
      "socmint_weight": 0.3,
      "base_score": 60.0,
      "final_score": 64.5
    },
    "category": "cyber",
    "published": "2025-11-13T10:30:00Z"
  }
}
```

## Understanding the Scores

### SOCMINT Raw Score Breakdown
The raw SOCMINT score (0-100) is calculated from:

| Factor | Points | Criteria |
|--------|--------|----------|
| **Follower Count** | 0-15 | <1k: 0, 1k-10k: 5, 10k-100k: 10, >100k: 15 |
| **Verified Status** | -10 | Penalty for verified accounts (lower imposter risk) |
| **Recent Activity** | 0-10 | Post within 7 days: +10 |
| **IOC Mentions** | 0-20 | CVEs, IPs, domains in posts (capped at 20) |

**Example Calculation:**
```
Profile: @threat_actor
- Followers: 150,000 → +15 points
- Verified: No → 0 points
- Last post: 2 days ago → +10 points
- Posts mention CVE-2024-0001 → +5 points
─────────────────────────────────────
Raw SOCMINT Score: 30 points

Weighted contribution: 30 × 0.3 = 9 points
Final score: 60 (base) + 9 = 69
```

### Score Impact Analysis

Use the utility functions to analyze impact:

```python
from threat_score_utils import calculate_score_impact

impact = calculate_score_impact(components)
# Returns:
# {
#   "total_score": 64.5,
#   "enhancement_percent": 7.5,
#   "factors": [
#     {"name": "SOCMINT", "impact": 4.5, "impact_percent": 7.0},
#     {"name": "Base Assessment", "impact": 60.0, "impact_percent": 93.0}
#   ]
# }
```

## Frontend Integration

### JavaScript Example
```javascript
// Fetch alert with scoring details
async function getAlertScoring(alertUuid) {
  const response = await fetch(`/alerts/${alertUuid}/scoring`, {
    headers: {
      'Authorization': `Bearer ${getToken()}`
    }
  });
  
  const { alert } = await response.json();
  return alert;
}

// Display score breakdown
function displayScoreBreakdown(alert) {
  const components = alert.threat_score_components;
  
  if (!components) {
    console.log('No scoring breakdown available');
    return;
  }
  
  const baseScore = components.base_score || 0;
  const socmintBoost = components.socmint_weighted || 0;
  const finalScore = components.final_score || alert.score;
  
  console.log(`Base Threat Score: ${baseScore}`);
  
  if (socmintBoost > 0) {
    const percent = ((socmintBoost / finalScore) * 100).toFixed(1);
    console.log(`SOCMINT Boost: +${socmintBoost} (+${percent}%)`);
    console.log(`  ↳ Raw SOCMINT: ${components.socmint_raw}`);
    console.log(`  ↳ Weight Applied: ${components.socmint_weight * 100}%`);
  }
  
  console.log(`Final Score: ${finalScore}`);
}

// Usage
const alert = await getAlertScoring('abc-123');
displayScoreBreakdown(alert);
```

### React Component Example
```jsx
import React from 'react';

function ScoreBreakdown({ components }) {
  if (!components || !components.socmint_weighted) {
    return <div>Standard threat assessment (no SOCMINT data)</div>;
  }
  
  const basePercent = (components.base_score / components.final_score) * 100;
  const socmintPercent = (components.socmint_weighted / components.final_score) * 100;
  
  return (
    <div className="score-breakdown">
      <h3>Threat Score: {components.final_score}</h3>
      
      <div className="score-bar">
        <div 
          className="base-score" 
          style={{ width: `${basePercent}%` }}
          title={`Base: ${components.base_score}`}
        />
        <div 
          className="socmint-boost" 
          style={{ width: `${socmintPercent}%` }}
          title={`SOCMINT: +${components.socmint_weighted}`}
        />
      </div>
      
      <div className="score-details">
        <div>
          <strong>Base Assessment:</strong> {components.base_score}
        </div>
        <div>
          <strong>SOCMINT Intelligence:</strong> +{components.socmint_weighted}
          <small> (from social media analysis)</small>
        </div>
      </div>
    </div>
  );
}

export default ScoreBreakdown;
```

## Python Integration

### Using Utility Functions
```python
from threat_score_utils import (
    format_score_components,
    calculate_score_impact,
    get_socmint_details,
    format_for_ui
)

# Get alert from API or DB
alert = fetch_alert('abc-123')
components = alert['threat_score_components']

# Format for display
formatted = format_score_components(components)
print(formatted['breakdown']['socmint'])

# Calculate impact
impact = calculate_score_impact(components)
print(f"SOCMINT contributed {impact['factors'][0]['impact_percent']}%")

# Get SOCMINT details
socmint = get_socmint_details(components)
for factor in socmint['estimated_factors']:
    print(f"{factor['factor']}: {factor['impact']}")

# Format for UI (charts, progress bars)
ui_data = format_for_ui(components)
for item in ui_data:
    print(f"{item['label']}: {item['value']} ({item['percentage']}%)")
```

## Database Schema

### Migration
```sql
-- Add threat_score_components column
ALTER TABLE alerts 
ADD COLUMN IF NOT EXISTS threat_score_components JSONB;

-- Index for faster queries
CREATE INDEX IF NOT EXISTS idx_alerts_threat_components 
ON alerts USING gin (threat_score_components);
```

### Querying
```sql
-- Alerts with SOCMINT contribution
SELECT uuid, title, score, threat_score_components
FROM alerts
WHERE threat_score_components->>'socmint_weighted' IS NOT NULL
ORDER BY (threat_score_components->>'socmint_weighted')::float DESC
LIMIT 10;

-- Alerts where SOCMINT boosted score >10%
SELECT 
  uuid, 
  title,
  score,
  (threat_score_components->>'socmint_weighted')::float as socmint_boost
FROM alerts
WHERE (threat_score_components->>'socmint_weighted')::float > 
      (threat_score_components->>'base_score')::float * 0.1;
```

## Use Cases

### 1. Analyst Dashboard
Display score breakdown with visual indicators:
- Base score (blue bar)
- SOCMINT boost (purple overlay)
- Tooltip with detailed factors

### 2. Alert Prioritization
Sort/filter by SOCMINT contribution:
```python
# High-priority: SOCMINT boost >15%
high_socmint = [
    a for a in alerts 
    if a['threat_score_components'].get('socmint_weighted', 0) > 
       a['threat_score_components'].get('base_score', 0) * 0.15
]
```

### 3. Reporting
Generate reports showing SOCMINT impact:
```python
total_alerts = len(alerts)
with_socmint = sum(1 for a in alerts if 'socmint_raw' in a.get('threat_score_components', {}))
avg_boost = sum(
    a['threat_score_components'].get('socmint_weighted', 0) 
    for a in alerts
) / total_alerts

print(f"SOCMINT Coverage: {with_socmint}/{total_alerts} ({with_socmint/total_alerts*100:.1f}%)")
print(f"Average Score Boost: +{avg_boost:.2f} points")
```

### 4. Threshold Alerts
Notify when SOCMINT significantly changes threat assessment:
```python
def check_significant_boost(alert):
    components = alert.get('threat_score_components', {})
    base = components.get('base_score', 0)
    boost = components.get('socmint_weighted', 0)
    
    if base > 0 and boost > base * 0.2:  # >20% boost
        send_notification(
            f"Alert {alert['uuid']} significantly boosted by SOCMINT: "
            f"{base} → {base + boost} (+{boost/base*100:.0f}%)"
        )
```

## Best Practices

### 1. Display Guidelines
- Always show both base and final scores
- Use visual indicators (colors, bars) for SOCMINT contribution
- Provide tooltip/expandable details for score factors
- Include timestamp of SOCMINT data freshness

### 2. Filtering & Sorting
- Allow filtering by SOCMINT presence
- Sort by SOCMINT contribution percentage
- Highlight alerts where SOCMINT changed threat level

### 3. Performance
- `threat_score_components` is JSONB, indexed with GIN
- Query performance: <100ms for typical queries
- Cache formatted breakdowns on frontend

### 4. Error Handling
```python
components = alert.get('threat_score_components')

if not components:
    # No scoring breakdown available
    display_simple_score(alert['score'])
elif 'socmint_raw' not in components:
    # Scored without SOCMINT
    display_base_score(components.get('base_score', alert['score']))
else:
    # Full breakdown available
    display_detailed_breakdown(components)
```

## Testing

Run test suite:
```bash
python3 tests/socmint/test_threat_score_utils.py
python3 demo_threat_score_api.py
```

## Support & Documentation

- **Metrics**: See `SOCMINT_METRICS.md` for cache performance tracking
- **Scoring Logic**: See `threat_engine.py::calculate_socmint_score()`
- **Utils**: See `threat_score_utils.py` for formatting helpers
- **Demo**: Run `demo_threat_score_api.py` for interactive examples

## Changelog

### v1.0 - 2025-11-13
- ✅ Added `threat_score_components` to alerts table
- ✅ Exposed components in `/alerts` and `/alerts/latest`
- ✅ Created `/alerts/<uuid>/scoring` detail endpoint
- ✅ Built formatting utilities in `threat_score_utils.py`
- ✅ Comprehensive test coverage
- ✅ Demo and documentation
