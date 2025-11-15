# Frontend Integration Guide - Phase 4 Coverage Dashboard

## Backend Endpoints (Production Ready)

### Summary
```
GET /api/monitoring/dashboard/summary
```
Returns:
```json
{
  "timestamp": "2025-11-15T06:47:32.123456",
  "total_locations": 15,
  "covered_locations": 10,
  "coverage_gaps": 5,
  "total_alerts_7d": 150,
  "synthetic_alerts_7d": 20,
  "synthetic_ratio_7d": 13.33
}
```

### Top Coverage Gaps
```
GET /api/monitoring/dashboard/top_gaps?limit=10&min_alerts_7d=5&max_age_hours=24
```
Returns:
```json
{
  "items": [
    {
      "country": "Serbia",
      "region": "Vojvodina",
      "issues": ["sparse", "stale"],
      "alert_count_7d": 2,
      "synthetic_count_7d": 1,
      "synthetic_ratio_7d": 50.0,
      "last_alert_age_hours": 36.5,
      "confidence_avg": 0.45
    }
  ],
  "count": 1
}
```

### Top Covered Locations
```
GET /api/monitoring/dashboard/top_covered?limit=10
```
Returns:
```json
{
  "items": [
    {
      "country": "France",
      "region": "Île-de-France",
      "alert_count_7d": 45,
      "alert_count_30d": 180,
      "synthetic_count_7d": 5,
      "synthetic_count_30d": 15,
      "synthetic_ratio_7d": 11.11,
      "confidence_avg": 0.78,
      "sources_count": 12
    }
  ],
  "count": 1
}
```

### Admin Trigger (Requires X-API-Key)
```
POST /admin/fallback/trigger?country=Serbia&region=Vojvodina
Header: X-API-Key: YOUR_ADMIN_KEY
```
Returns:
```json
{
  "ok": true,
  "count": 1,
  "attempts": [
    {
      "country": "Serbia",
      "region": "Vojvodina",
      "issues": ["sparse"],
      "feed_type": "country",
      "feeds_used": ["https://www.danas.rs/feed/"],
      "fetched_items": 15,
      "created_alerts": 10,
      "status": "success",
      "error": null,
      "timestamp": 1731654123.456
    }
  ],
  "timestamp": "2025-11-15T06:48:43.123456Z"
}
```

---

## Next.js Setup

### 1. Environment Variables

`.env.local`:
```bash
NEXT_PUBLIC_BACKEND_URL=https://your-backend-host
BACKEND_ADMIN_API_KEY=your_admin_key_here
```

### 2. API Client

`lib/api.ts`:
```typescript
export const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL!;

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const MonitoringAPI = {
  summary: () => fetchJson<{
    timestamp: string;
    total_locations: number;
    covered_locations: number;
    coverage_gaps: number;
    total_alerts_7d: number;
    synthetic_alerts_7d: number;
    synthetic_ratio_7d: number;
  }>('/api/monitoring/dashboard/summary'),

  topGaps: (q?: { limit?: number; min_alerts_7d?: number; max_age_hours?: number }) =>
    fetchJson<{ items: any[]; count: number }>(
      `/api/monitoring/dashboard/top_gaps?limit=${q?.limit ?? 10}&min_alerts_7d=${q?.min_alerts_7d ?? 5}&max_age_hours=${q?.max_age_hours ?? 24}`
    ),

  topCovered: (limit = 10) =>
    fetchJson<{ items: any[]; count: number }>(`/api/monitoring/dashboard/top_covered?limit=${limit}`),
};
```

### 3. SWR Hooks

`hooks/useMonitoring.ts`:
```typescript
import useSWR from 'swr';
import { MonitoringAPI } from '@/lib/api';

export function useSummary() {
  const { data, error, isLoading, mutate } = useSWR('summary', MonitoringAPI.summary, { refreshInterval: 60000 });
  return { summary: data, error, isLoading, refresh: mutate };
}

export function useTopGaps(params?: { limit?: number; min_alerts_7d?: number; max_age_hours?: number }) {
  const key = `top_gaps:${JSON.stringify(params || {})}`;
  const { data, error, isLoading, mutate } = useSWR(key, () => MonitoringAPI.topGaps(params), { refreshInterval: 60000 });
  return { gaps: data?.items || [], count: data?.count || 0, error, isLoading, refresh: mutate };
}

export function useTopCovered(limit = 10) {
  const { data, error, isLoading, mutate } = useSWR(`top_covered:${limit}`, () => MonitoringAPI.topCovered(limit), { refreshInterval: 60000 });
  return { covered: data?.items || [], count: data?.count || 0, error, isLoading, refresh: mutate };
}
```

### 4. Secure Admin Proxy (Pages Router)

`pages/api/admin/fallback/trigger.ts`:
```typescript
import type { NextApiRequest, NextApiResponse } from 'next';

const ADMIN_KEY = process.env.BACKEND_ADMIN_API_KEY!;
const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL!;

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  
  // Optional: Add your own auth check here (e.g., session validation)
  
  try {
    const { country, region } = req.body || {};
    const url = new URL('/admin/fallback/trigger', API_BASE);
    if (country) url.searchParams.set('country', country);
    if (region) url.searchParams.set('region', region);

    const resp = await fetch(url.toString(), {
      method: 'POST',
      headers: { 'X-API-Key': ADMIN_KEY },
    });
    const json = await resp.json();
    return res.status(resp.status).json(json);
  } catch (e: any) {
    return res.status(500).json({ error: 'Proxy failed', details: e?.message });
  }
}
```

**App Router version:** `app/api/admin/fallback/trigger/route.ts`:
```typescript
import { NextRequest, NextResponse } from 'next/server';

const ADMIN_KEY = process.env.BACKEND_ADMIN_API_KEY!;
const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL!;

export async function POST(req: NextRequest) {
  try {
    const { country, region } = await req.json();
    const url = new URL('/admin/fallback/trigger', API_BASE);
    if (country) url.searchParams.set('country', country);
    if (region) url.searchParams.set('region', region);

    const resp = await fetch(url.toString(), {
      method: 'POST',
      headers: { 'X-API-Key': ADMIN_KEY },
    });
    const json = await resp.json();
    return NextResponse.json(json, { status: resp.status });
  } catch (e: any) {
    return NextResponse.json({ error: 'Proxy failed', details: e?.message }, { status: 500 });
  }
}
```

---

## UI Components

### Summary Cards
`components/SummaryCards.tsx`:
```tsx
import React from 'react';

export function SummaryCards({ data }: { data?: {
  total_locations: number;
  covered_locations: number;
  coverage_gaps: number;
  synthetic_ratio_7d: number;
}}) {
  if (!data) return null;
  const { total_locations, covered_locations, coverage_gaps, synthetic_ratio_7d } = data;
  
  return (
    <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))' }}>
      <Card title="Total Locations" value={total_locations} />
      <Card title="Covered Locations" value={covered_locations} />
      <Card title="Coverage Gaps" value={coverage_gaps} />
      <Card title="Synthetic Ratio (7d)" value={`${synthetic_ratio_7d}%`} bar={synthetic_ratio_7d} />
    </div>
  );
}

function Card({ title, value, bar }: { title: string; value: any; bar?: number }) {
  return (
    <div style={{ padding: 12, border: '1px solid #e5e7eb', borderRadius: 8 }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{title}</div>
      <div style={{ fontSize: 20, fontWeight: 600 }}>{value}</div>
      {typeof bar === 'number' && (
        <div style={{ marginTop: 8, background: '#f3f4f6', height: 6, borderRadius: 999 }}>
          <div style={{
            width: `${Math.min(100, Math.max(0, bar))}%`,
            height: 6,
            borderRadius: 999,
            background: bar > 20 ? '#ef4444' : bar > 10 ? '#f59e0b' : '#10b981'
          }} />
        </div>
      )}
    </div>
  );
}
```

### Top Gaps Table
`components/TopGapsTable.tsx`:
```tsx
import React from 'react';

export function TopGapsTable({ 
  items, 
  onTrigger 
}: { 
  items: Array<{
    country: string;
    region?: string;
    issues: string[];
    alert_count_7d: number;
    synthetic_count_7d: number;
    synthetic_ratio_7d: number;
    last_alert_age_hours: number;
    confidence_avg: number;
  }>; 
  onTrigger: (country: string, region?: string) => void; 
}) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <Th>Country</Th>
          <Th>Region</Th>
          <Th>Issues</Th>
          <Th>Alerts (7d)</Th>
          <Th>Synthetic (7d)</Th>
          <Th>Ratio</Th>
          <Th>Last Alert Age</Th>
          <Th>Confidence</Th>
          <Th>Action</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((g, i) => (
          <tr key={i} style={{ borderTop: '1px solid #e5e7eb' }}>
            <Td>{g.country}</Td>
            <Td>{g.region || '—'}</Td>
            <Td>
              {(g.issues || []).map((issue) => (
                <Badge key={issue} text={issue} />
              ))}
            </Td>
            <Td>{g.alert_count_7d}</Td>
            <Td>{g.synthetic_count_7d ?? 0}</Td>
            <Td>{g.synthetic_ratio_7d ?? 0}%</Td>
            <Td>{Math.round(g.last_alert_age_hours)}h</Td>
            <Td>{g.confidence_avg?.toFixed(2) ?? '—'}</Td>
            <Td>
              <button 
                onClick={() => onTrigger(g.country, g.region)}
                style={{ padding: '6px 10px', cursor: 'pointer' }}
              >
                Trigger
              </button>
            </Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Th({ children }: any) {
  return <th style={{ textAlign: 'left', fontSize: 12, color: '#6b7280', padding: 8 }}>{children}</th>;
}

function Td({ children }: any) {
  return <td style={{ padding: 8 }}>{children}</td>;
}

function Badge({ text }: { text: string }) {
  const color = text === 'stale' ? '#f59e0b' : text === 'sparse' ? '#ef4444' : '#6b7280';
  return (
    <span style={{
      background: color,
      color: 'white',
      padding: '2px 6px',
      borderRadius: 6,
      marginRight: 6,
      fontSize: 11
    }}>
      {text}
    </span>
  );
}
```

### Top Covered Table (CORRECTED - Only Uses Returned Fields)
`components/TopCoveredTable.tsx`:
```tsx
import React from 'react';

export function TopCoveredTable({ 
  items 
}: { 
  items: Array<{
    country: string;
    region?: string;
    alert_count_7d: number;
    alert_count_30d: number;
    synthetic_count_7d: number;
    synthetic_count_30d: number;
    synthetic_ratio_7d: number;
    confidence_avg: number;
    sources_count: number;
  }> 
}) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <Th>Country</Th>
          <Th>Region</Th>
          <Th>Alerts (7d)</Th>
          <Th>Alerts (30d)</Th>
          <Th>Synth. (7d)</Th>
          <Th>Synth. Ratio (7d)</Th>
          <Th>Confidence</Th>
          <Th>Sources</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((item, i) => (
          <tr key={i} style={{ borderTop: '1px solid #e5e7eb' }}>
            <Td>{item.country}</Td>
            <Td>{item.region || '—'}</Td>
            <Td>{item.alert_count_7d}</Td>
            <Td>{item.alert_count_30d}</Td>
            <Td>{item.synthetic_count_7d ?? 0}</Td>
            <Td>
              <span style={{
                color: item.synthetic_ratio_7d > 20 ? '#ef4444' : item.synthetic_ratio_7d > 10 ? '#f59e0b' : '#10b981'
              }}>
                {item.synthetic_ratio_7d?.toFixed(1) ?? 0}%
              </span>
            </Td>
            <Td>{item.confidence_avg?.toFixed(2) ?? '—'}</Td>
            <Td>{item.sources_count ?? 0}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Th({ children }: any) {
  return <th style={{ textAlign: 'left', fontSize: 12, color: '#6b7280', padding: 8 }}>{children}</th>;
}

function Td({ children }: any) {
  return <td style={{ padding: 8 }}>{children}</td>;
}
```

---

## Complete Dashboard Page

### Pages Router
`pages/admin/coverage.tsx`:
```tsx
import { useSummary, useTopGaps, useTopCovered } from '@/hooks/useMonitoring';
import { SummaryCards } from '@/components/SummaryCards';
import { TopGapsTable } from '@/components/TopGapsTable';
import { TopCoveredTable } from '@/components/TopCoveredTable';

export default function CoverageDashboard() {
  const { summary, isLoading: summaryLoading } = useSummary();
  const { gaps, refresh: refreshGaps, isLoading: gapsLoading } = useTopGaps({ limit: 10 });
  const { covered, isLoading: coveredLoading } = useTopCovered(10);

  async function triggerFallback(country: string, region?: string) {
    try {
      const res = await fetch('/api/admin/fallback/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ country, region }),
      });
      const data = await res.json();
      console.log('Fallback triggered:', data);
      // Refresh gaps after 2 seconds to see changes
      setTimeout(refreshGaps, 2000);
    } catch (e) {
      console.error('Trigger failed:', e);
    }
  }

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 16 }}>Coverage Dashboard</h1>
      
      {summaryLoading ? <div>Loading summary...</div> : <SummaryCards data={summary} />}
      
      <h2 style={{ marginTop: 24, marginBottom: 12, fontSize: 18, fontWeight: 600 }}>
        Top Coverage Gaps
      </h2>
      {gapsLoading ? (
        <div>Loading gaps...</div>
      ) : (
        <TopGapsTable items={gaps} onTrigger={triggerFallback} />
      )}
      
      <h2 style={{ marginTop: 24, marginBottom: 12, fontSize: 18, fontWeight: 600 }}>
        Top Covered Locations
      </h2>
      {coveredLoading ? (
        <div>Loading covered locations...</div>
      ) : (
        <TopCoveredTable items={covered} />
      )}
    </div>
  );
}
```

### App Router
`app/admin/coverage/page.tsx`:
```tsx
'use client';

import { useSummary, useTopGaps, useTopCovered } from '@/hooks/useMonitoring';
import { SummaryCards } from '@/components/SummaryCards';
import { TopGapsTable } from '@/components/TopGapsTable';
import { TopCoveredTable } from '@/components/TopCoveredTable';

export default function CoverageDashboard() {
  const { summary, isLoading: summaryLoading } = useSummary();
  const { gaps, refresh: refreshGaps, isLoading: gapsLoading } = useTopGaps({ limit: 10 });
  const { covered, isLoading: coveredLoading } = useTopCovered(10);

  async function triggerFallback(country: string, region?: string) {
    try {
      const res = await fetch('/api/admin/fallback/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ country, region }),
      });
      const data = await res.json();
      console.log('Fallback triggered:', data);
      setTimeout(refreshGaps, 2000);
    } catch (e) {
      console.error('Trigger failed:', e);
    }
  }

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 16 }}>Coverage Dashboard</h1>
      
      {summaryLoading ? <div>Loading summary...</div> : <SummaryCards data={summary} />}
      
      <h2 style={{ marginTop: 24, marginBottom: 12, fontSize: 18, fontWeight: 600 }}>
        Top Coverage Gaps
      </h2>
      {gapsLoading ? (
        <div>Loading gaps...</div>
      ) : (
        <TopGapsTable items={gaps} onTrigger={triggerFallback} />
      )}
      
      <h2 style={{ marginTop: 24, marginBottom: 12, fontSize: 18, fontWeight: 600 }}>
        Top Covered Locations
      </h2>
      {coveredLoading ? (
        <div>Loading covered locations...</div>
      ) : (
        <TopCoveredTable items={covered} />
      )}
    </div>
  );
}
```

---

## Grafana JSON API Setup

1. **Install JSON API Plugin:**
   - Dashboard → Settings → Data Sources → Add data source → JSON API

2. **Configure:**
   - URL: `https://your-backend-host`
   - Method: GET
   - No authentication needed (if endpoints are public) or add headers

3. **Panel Examples:**

   **Stat Panel - Synthetic Ratio:**
   - Query: `/api/monitoring/dashboard/summary`
   - Field: `synthetic_ratio_7d`
   - Unit: Percent
   - Thresholds: Green 0-10, Orange 10-20, Red 20+

   **Table Panel - Top Gaps:**
   - Query: `/api/monitoring/dashboard/top_gaps?limit=10`
   - Transform: Extract fields → `items[*]`
   - Columns: country, region, issues, alert_count_7d, synthetic_ratio_7d

   **Stat Panel - Coverage Ratio:**
   - Query: `/api/monitoring/dashboard/summary`
   - Transform: Add field from calculation → `covered_locations / total_locations * 100`
   - Unit: Percent

---

## Testing Checklist

- [ ] Backend endpoints respond correctly
  ```bash
  curl -s localhost:8080/api/monitoring/dashboard/summary | python3 -m json.tool
  curl -s "localhost:8080/api/monitoring/dashboard/top_gaps?limit=5" | python3 -m json.tool
  curl -s "localhost:8080/api/monitoring/dashboard/top_covered?limit=5" | python3 -m json.tool
  ```

- [ ] Admin trigger works (replace YOUR_KEY):
  ```bash
  curl -s -X POST \
    -H "X-API-Key: YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{"country":"Serbia"}' \
    http://localhost:8080/admin/fallback/trigger | python3 -m json.tool
  ```

- [ ] Frontend fetches data without CORS errors
- [ ] Trigger button creates fallback attempts
- [ ] SWR auto-refreshes every 60 seconds
- [ ] Synthetic ratio color coding works (green <10%, orange 10-20%, red >20%)

---

## Next Steps (Optional)

**Phase 4c - Trend Persistence:**
- Add hourly/daily snapshot of `synthetic_ratio_7d` to DB
- Create `/api/monitoring/trends?days=7` endpoint
- Build time-series chart in frontend

**Advanced Filtering:**
- Add region selector dropdown in UI
- Filter by issues (sparse/stale)
- Date range picker for historical data (requires persistence)

**Alerts:**
- Send Slack/email when synthetic_ratio > 25%
- Notify when coverage_gaps increases by >20% hour-over-hour

