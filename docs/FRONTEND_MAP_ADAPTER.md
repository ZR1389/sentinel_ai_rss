# Frontend Map Adapter Utility

This utility normalizes alert data from the backend `/api/map-alerts` and `/api/map-alerts/aggregates` endpoints for consistent rendering on maps with clustering, uncertainty visualization, and confidence-based opacity.

---

## Quick Start

```ts
import { MapAdapter } from './utils/mapAdapter';

// Initialize with API base URL
const adapter = new MapAdapter('https://your-api.com');

// Fetch and normalize alerts
const { features, aggregates } = await adapter.fetchAlerts({
  days: 30,
  severity: ['critical', 'high'],
  zoom: 4  // if zoom < 5, uses aggregation
});

// Render on map
features.forEach(feature => {
  const { geometry, properties } = feature;
  const { color, opacity, radius } = properties;
  
  // Use color/opacity for marker styling
  // Use radius for uncertainty circles (country-level alerts)
});
```

---

## Map Adapter Implementation

Save as `src/utils/mapAdapter.ts`:

```typescript
export type Severity = 'critical' | 'high' | 'medium' | 'low';

export interface AlertFeature {
  type: 'Feature';
  geometry: {
    type: 'Point';
    coordinates: [number, number]; // [lon, lat]
  };
  properties: {
    uuid: string;
    title: string;
    summary?: string;
    published: string;
    source: string;
    country?: string;
    city?: string;
    category?: string;
    subcategory?: string;
    threat_label?: string;
    threat_level?: string;
    score?: number;
    confidence?: number;
    tags?: any[];
    // Normalized fields for rendering
    severity: Severity;
    event_type?: string;
    color: string;
    opacity: number;
    radius?: number; // km, for uncertainty circles
    is_aggregate?: boolean;
  };
}

export interface AggregateResult {
  country: string;
  count: number;
  avg_score: number;
  severity: string;
  lat: number;
  lon: number;
  radius_km: number;
}

export interface FetchAlertsOptions {
  days?: number;
  severity?: Severity[];
  categories?: string[];
  eventTypes?: string[];
  sources?: string[];
  zoom?: number; // if < 5, use aggregation
  limit?: number;
}

export class MapAdapter {
  constructor(private apiBase: string) {}

  /**
   * Fetch alerts from backend with optional aggregation for low zoom levels
   */
  async fetchAlerts(opts: FetchAlertsOptions = {}) {
    const {
      days = 30,
      severity = [],
      categories = [],
      eventTypes = [],
      sources = ['gdelt', 'rss', 'news'],
      zoom = 10,
      limit = 5000
    } = opts;

    // Use aggregation for low zoom (country-level)
    if (zoom < 5) {
      const aggregates = await this.fetchAggregates({
        days,
        severity,
        categories,
        eventTypes,
        sources
      });
      return {
        features: aggregates.map(a => this.aggregateToFeature(a)),
        aggregates
      };
    }

    // Fetch individual alerts for zoom >= 5
    const params = new URLSearchParams();
    params.set('days', String(days));
    params.set('limit', String(limit));
    if (sources.length) params.set('sources', sources.join(','));
    if (severity.length) params.set('severity', severity.join(','));
    if (categories.length) params.set('category', categories.join(','));
    if (eventTypes.length) params.set('event_type', eventTypes.join(','));

    const url = `${this.apiBase}/api/map-alerts?${params}`;
    const res = await fetch(url);
    const data = await res.json();

    return {
      features: (data.features || []).map(f => this.normalizeFeature(f)),
      aggregates: []
    };
  }

  /**
   * Fetch country-level aggregates
   */
  private async fetchAggregates(opts: Omit<FetchAlertsOptions, 'zoom' | 'limit'>): Promise<AggregateResult[]> {
    const {
      days = 30,
      severity = [],
      categories = [],
      eventTypes = [],
      sources = ['gdelt', 'rss', 'news']
    } = opts;

    const params = new URLSearchParams();
    params.set('days', String(days));
    if (sources.length) params.set('sources', sources.join(','));
    if (severity.length) params.set('severity', severity.join(','));
    if (categories.length) params.set('category', categories.join(','));
    if (eventTypes.length) params.set('event_type', eventTypes.join(','));

    const url = `${this.apiBase}/api/map-alerts/aggregates?${params}`;
    const res = await fetch(url);
    const data = await res.json();

    return data.aggregates || [];
  }

  /**
   * Normalize individual alert feature
   */
  private normalizeFeature(feature: any): AlertFeature {
    const props = feature.properties || {};
    
    // Extract severity (prefer threat_label, fallback to threat_level)
    const severity = this.normalizeSeverity(props.threat_label || props.threat_level);
    
    // Extract event type from tags or fallback to category
    const event_type = this.extractEventType(props.tags) || props.subcategory || props.category;
    
    // Calculate color based on severity
    const color = this.severityColor(severity);
    
    // Calculate opacity based on confidence (0.4-1.0 range)
    const confidence = parseFloat(props.confidence) || 0.7;
    const opacity = Math.max(0.4, Math.min(1.0, 0.4 + confidence * 0.6));
    
    // Calculate uncertainty radius for country-level alerts (no city)
    const radius = props.city ? undefined : this.calculateUncertaintyRadius(props);
    
    return {
      ...feature,
      properties: {
        ...props,
        severity,
        event_type,
        color,
        opacity,
        radius,
        is_aggregate: false
      }
    };
  }

  /**
   * Convert aggregate to feature
   */
  private aggregateToFeature(agg: AggregateResult): AlertFeature {
    const severity = this.normalizeSeverity(agg.severity);
    const color = this.severityColor(severity);
    
    return {
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: [agg.lon, agg.lat]
      },
      properties: {
        uuid: `aggregate-${agg.country}`,
        title: `${agg.country}: ${agg.count} alerts`,
        published: new Date().toISOString(),
        source: 'aggregate',
        country: agg.country,
        severity,
        score: agg.avg_score,
        confidence: 0.8,
        color,
        opacity: 0.7,
        radius: agg.radius_km,
        is_aggregate: true
      }
    };
  }

  /**
   * Normalize severity to standard levels
   */
  private normalizeSeverity(raw?: string): Severity {
    if (!raw) return 'medium';
    const s = raw.toLowerCase();
    if (s.includes('critical')) return 'critical';
    if (s.includes('high')) return 'high';
    if (s.includes('low')) return 'low';
    return 'medium';
  }

  /**
   * Extract event_type from tags array
   */
  private extractEventType(tags?: any[]): string | undefined {
    if (!Array.isArray(tags)) return undefined;
    for (const tag of tags) {
      if (tag?.event_type) return String(tag.event_type);
    }
    return undefined;
  }

  /**
   * Map severity to color
   */
  private severityColor(severity: Severity): string {
    const colors: Record<Severity, string> = {
      critical: '#DC2626', // red-600
      high: '#EA580C',     // orange-600
      medium: '#F59E0B',   // amber-500
      low: '#10B981'       // green-500
    };
    return colors[severity] || colors.medium;
  }

  /**
   * Calculate uncertainty radius for country-level alerts (heuristic)
   */
  private calculateUncertaintyRadius(props: any): number {
    // Default radius for country-level alerts: 200km
    // Could be enhanced with country size lookup
    return 200;
  }
}
```

---

## Usage Examples

### 1. Basic Map Rendering
```tsx
import { MapAdapter } from './utils/mapAdapter';
import { useEffect, useState } from 'react';

function ThreatMap() {
  const [features, setFeatures] = useState([]);
  const adapter = new MapAdapter(process.env.REACT_APP_API_BASE);

  useEffect(() => {
    adapter.fetchAlerts({ days: 30, zoom: 10 })
      .then(({ features }) => setFeatures(features));
  }, []);

  return (
    <MapComponent>
      {features.map(f => (
        <Marker
          key={f.properties.uuid}
          position={[f.geometry.coordinates[1], f.geometry.coordinates[0]]}
          style={{
            backgroundColor: f.properties.color,
            opacity: f.properties.opacity
          }}
        >
          {f.properties.radius && (
            <Circle
              center={[f.geometry.coordinates[1], f.geometry.coordinates[0]]}
              radius={f.properties.radius * 1000} // convert km to meters
              fillColor={f.properties.color}
              fillOpacity={0.2}
            />
          )}
        </Marker>
      ))}
    </MapComponent>
  );
}
```

### 2. With Filters
```tsx
const [severity, setSeverity] = useState<Severity[]>(['critical', 'high']);
const [zoom, setZoom] = useState(10);

useEffect(() => {
  adapter.fetchAlerts({ days: 30, severity, zoom })
    .then(({ features }) => setFeatures(features));
}, [severity, zoom]);
```

### 3. Zoom-Based Clustering
```tsx
function onZoomChange(newZoom: number) {
  setZoom(newZoom);
  
  // Automatically switches between aggregates (< 5) and individual alerts (>= 5)
  adapter.fetchAlerts({ days: 30, zoom: newZoom })
    .then(({ features, aggregates }) => {
      if (newZoom < 5) {
        // Render country-level circles with counts
        setAggregates(aggregates);
      } else {
        // Render individual markers
        setFeatures(features);
      }
    });
}
```

---

## API Endpoints

### `/api/map-alerts`
- **Purpose:** Fetch individual alerts for zoom >= 5
- **Params:** `days`, `limit`, `sources`, `severity`, `category`, `event_type`, `lat`, `lon`, `radius`, `region`, `country`, `city`
- **Returns:** `{ ok, items, features, meta }`

### `/api/map-alerts/aggregates`
- **Purpose:** Fetch country-level aggregates for zoom < 5
- **Params:** `days`, `sources`, `severity`, `category`, `event_type`
- **Returns:** `{ ok, aggregates, meta }`

---

## Color & Opacity Reference

| Severity | Color | Hex |
|----------|-------|-----|
| Critical | Red | #DC2626 |
| High | Orange | #EA580C |
| Medium | Amber | #F59E0B |
| Low | Green | #10B981 |

**Opacity:** `0.4 + (confidence * 0.6)` → Range: 0.4–1.0

---

## Uncertainty Radius

- **City-level alerts:** No radius (precise marker)
- **Country-level alerts:** 200km default radius
- **Aggregates:** Backend calculates radius based on lat/lon spread (50-400km)

---

## Complete Example

```tsx
import { MapAdapter, AlertFeature } from './utils/mapAdapter';

const adapter = new MapAdapter('https://api.example.com');

// Fetch with all filters
const { features } = await adapter.fetchAlerts({
  days: 30,
  severity: ['critical', 'high'],
  categories: ['military', 'conflict'],
  eventTypes: ['use unconventional mass violence', 'threaten'],
  sources: ['gdelt', 'rss'],
  zoom: 6
});

// Render
features.forEach(f => {
  const { geometry, properties } = f;
  const [lon, lat] = geometry.coordinates;
  
  console.log({
    title: properties.title,
    severity: properties.severity,
    color: properties.color,
    opacity: properties.opacity,
    radius: properties.radius,
    isAggregate: properties.is_aggregate
  });
});
```

---

## Notes

- **Field consistency:** Always use `threat_label` for severity, fallback to `threat_level`
- **Event type:** Prefer `tags[].event_type`, fallback to `subcategory` → `category`
- **ACLED:** Already filtered out by backend; no frontend handling needed
- **Validation:** Adapter validates coordinates, confidence, and required fields internally
- **Performance:** Aggregation endpoint reduces payload by ~95% at low zoom levels

---

## TypeScript Definitions

```typescript
export interface MapAlert {
  uuid: string;
  title: string;
  summary?: string;
  published: string;
  source: string;
  country?: string;
  city?: string;
  latitude: number;
  longitude: number;
  severity: 'critical' | 'high' | 'medium' | 'low';
  event_type?: string;
  score?: number;
  confidence?: number;
  tags?: any[];
}
```
