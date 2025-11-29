# Frontend Stats Dashboard Integration Guide

## Overview Stats API Enhancements

### What Changed
1. **Plan-based limits** - `window_days` capped by user plan (FREE=7d, PRO=30d, ENTERPRISE/VIP=90d)
2. **Severity percentages** - Added `critical_pct`, `high_pct`, `medium_pct`, `low_pct`, `total`
3. **Tracked locations** - Now counts distinct alert locations (city/country) with coordinates, not saved user contexts

---

## API Response Structure

### Endpoint
```
GET /api/stats/overview?days=7
Authorization: Bearer <token>
```

### Response
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
  "window_days": 7,
  "max_window_days": 30,
  "weekly_trends": [
    {"date": "2025-11-14", "count": 156},
    {"date": "2025-11-15", "count": 189},
    {"date": "2025-11-16", "count": 203},
    {"date": "2025-11-17", "count": 178},
    {"date": "2025-11-18", "count": 195},
    {"date": "2025-11-19", "count": 167},
    {"date": "2025-11-20", "count": 155}
  ],
  "top_regions": [
    {"region": "Eastern Europe", "count": 245, "percentage": 35.5},
    {"region": "Middle East", "count": 189, "percentage": 27.4},
    {"region": "Asia", "count": 156, "percentage": 22.6},
    {"region": "North America", "count": 78, "percentage": 11.3},
    {"region": "Unknown", "count": 22, "percentage": 3.2}
  ],
  "severity_breakdown": {
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
}
```

---

## Frontend Components & Use Cases

### 1. Dashboard Overview Cards

**KPI Cards with Trend Indicators**
```tsx
// components/DashboardStats.tsx
import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, Shield, MapPin, MessageSquare, Eye } from 'lucide-react';

interface StatsData {
  threats_7d: number;
  threats_30d: number;
  trend_7d: number;
  active_monitors: number;
  tracked_locations: number;
  chat_messages_month: number;
}

export function DashboardStats() {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/stats/overview', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
    })
      .then(res => res.json())
      .then(data => {
        setStats(data);
        setLoading(false);
      });
  }, []);

  if (loading) return <div>Loading...</div>;

  const cards = [
    {
      title: "Threats (7d)",
      value: stats.threats_7d,
      trend: stats.trend_7d,
      icon: Shield,
      color: "text-red-500"
    },
    {
      title: "Active Monitors",
      value: stats.active_monitors,
      icon: Eye,
      color: "text-blue-500"
    },
    {
      title: "Tracked Locations",
      value: stats.tracked_locations,
      icon: MapPin,
      color: "text-green-500"
    },
    {
      title: "Chat Messages",
      value: stats.chat_messages_month,
      icon: MessageSquare,
      color: "text-purple-500"
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card, idx) => (
        <div key={idx} className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500 dark:text-gray-400">{card.title}</p>
              <p className="text-3xl font-bold mt-2">{card.value.toLocaleString()}</p>
              {card.trend !== undefined && (
                <div className={`flex items-center mt-2 text-sm ${
                  card.trend > 0 ? 'text-red-500' : card.trend < 0 ? 'text-green-500' : 'text-gray-500'
                }`}>
                  {card.trend > 0 ? <TrendingUp className="w-4 h-4 mr-1" /> : 
                   card.trend < 0 ? <TrendingDown className="w-4 h-4 mr-1" /> : null}
                  <span>{Math.abs(card.trend)}% vs prev week</span>
                </div>
              )}
            </div>
            <card.icon className={`w-12 h-12 ${card.color}`} />
          </div>
        </div>
      ))}
    </div>
  );
}
```

---

### 2. Severity Breakdown Chart

**Donut Chart with Percentages**
```tsx
// components/SeverityChart.tsx
import { Doughnut } from 'react-chartjs-2';

interface SeverityBreakdown {
  critical: number;
  high: number;
  medium: number;
  low: number;
  critical_pct: number;
  high_pct: number;
  medium_pct: number;
  low_pct: number;
  total: number;
}

export function SeverityChart({ breakdown }: { breakdown: SeverityBreakdown }) {
  const data = {
    labels: ['Critical', 'High', 'Medium', 'Low'],
    datasets: [{
      data: [breakdown.critical, breakdown.high, breakdown.medium, breakdown.low],
      backgroundColor: ['#EF4444', '#F59E0B', '#3B82F6', '#10B981'],
      borderWidth: 2,
      borderColor: '#fff'
    }]
  };

  const options = {
    plugins: {
      legend: { position: 'bottom' as const },
      tooltip: {
        callbacks: {
          label: (context: any) => {
            const label = context.label || '';
            const value = context.parsed;
            const percentage = breakdown[`${label.toLowerCase()}_pct`];
            return `${label}: ${value} (${percentage}%)`;
          }
        }
      }
    }
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold mb-4">Threat Severity Distribution</h3>
      <Doughnut data={data} options={options} />
      <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <div className="flex items-center justify-between">
          <span className="flex items-center">
            <span className="w-3 h-3 rounded-full bg-red-500 mr-2"></span>
            Critical
          </span>
          <span className="font-semibold">{breakdown.critical_pct}%</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center">
            <span className="w-3 h-3 rounded-full bg-orange-500 mr-2"></span>
            High
          </span>
          <span className="font-semibold">{breakdown.high_pct}%</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center">
            <span className="w-3 h-3 rounded-full bg-blue-500 mr-2"></span>
            Medium
          </span>
          <span className="font-semibold">{breakdown.medium_pct}%</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center">
            <span className="w-3 h-3 rounded-full bg-green-500 mr-2"></span>
            Low
          </span>
          <span className="font-semibold">{breakdown.low_pct}%</span>
        </div>
      </div>
    </div>
  );
}
```

---

### 3. Weekly Trends Line Chart

**Time Series with Plan-Based Window**
```tsx
// components/TrendsChart.tsx
import { Line } from 'react-chartjs-2';
import { useState } from 'react';

interface Trend {
  date: string;
  count: number;
}

export function TrendsChart({ 
  trends, 
  windowDays, 
  maxWindowDays 
}: { 
  trends: Trend[]; 
  windowDays: number; 
  maxWindowDays: number;
}) {
  const [selectedWindow, setSelectedWindow] = useState(windowDays);

  const data = {
    labels: trends.map(t => new Date(t.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })),
    datasets: [{
      label: 'Threat Count',
      data: trends.map(t => t.count),
      borderColor: '#3B82F6',
      backgroundColor: 'rgba(59, 130, 246, 0.1)',
      tension: 0.3,
      fill: true
    }]
  };

  const options = {
    responsive: true,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items: any) => new Date(trends[items[0].dataIndex].date).toLocaleDateString(),
          label: (item: any) => `Threats: ${item.parsed.y}`
        }
      }
    },
    scales: {
      y: { beginAtZero: true, ticks: { precision: 0 } }
    }
  };

  const availableWindows = [7, 30, 90].filter(w => w <= maxWindowDays);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Threat Trends</h3>
        <div className="flex gap-2">
          {availableWindows.map(days => (
            <button
              key={days}
              onClick={() => {
                setSelectedWindow(days);
                // Refetch with new window
                window.location.search = `?days=${days}`;
              }}
              className={`px-3 py-1 rounded text-sm ${
                selectedWindow === days
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300'
              }`}
            >
              {days}d
            </button>
          ))}
          {maxWindowDays < 90 && (
            <span className="text-xs text-gray-500 self-center ml-2">
              Upgrade for 90d view
            </span>
          )}
        </div>
      </div>
      <Line data={data} options={options} />
    </div>
  );
}
```

---

### 4. Regional Threat Map

**Top Regions with Percentages**
```tsx
// components/RegionsTable.tsx
export function RegionsTable({ regions }: { regions: Array<{region: string, count: number, percentage: number}> }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold mb-4">Top Threat Regions</h3>
      <div className="space-y-3">
        {regions.map((region, idx) => (
          <div key={idx} className="flex items-center">
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium">{region.region}</span>
                <span className="text-sm text-gray-500">{region.count} threats</span>
              </div>
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                <div 
                  className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${region.percentage}%` }}
                />
              </div>
            </div>
            <span className="ml-3 text-sm font-semibold text-gray-700 dark:text-gray-300">
              {region.percentage.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

### 5. Complete Dashboard Layout

**Full Page Integration**
```tsx
// pages/dashboard.tsx
import { useEffect, useState } from 'react';
import { DashboardStats } from '@/components/DashboardStats';
import { SeverityChart } from '@/components/SeverityChart';
import { TrendsChart } from '@/components/TrendsChart';
import { RegionsTable } from '@/components/RegionsTable';

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const token = localStorage.getItem('token');
        const res = await fetch('/api/stats/overview', {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (!res.ok) throw new Error('Failed to fetch stats');
        
        const data = await res.json();
        setStats(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
    
    // Auto-refresh every 2 minutes
    const interval = setInterval(fetchStats, 120000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div className="flex items-center justify-center h-screen">Loading...</div>;
  if (error) return <div className="text-red-500">Error: {error}</div>;

  return (
    <div className="container mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Security Dashboard</h1>
        <div className="text-sm text-gray-500">
          Last updated: {new Date(stats.updated_at).toLocaleTimeString()}
        </div>
      </div>

      {/* KPI Cards */}
      <DashboardStats 
        threats_7d={stats.threats_7d}
        threats_30d={stats.threats_30d}
        trend_7d={stats.trend_7d}
        active_monitors={stats.active_monitors}
        tracked_locations={stats.tracked_locations}
        chat_messages_month={stats.chat_messages_month}
      />

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TrendsChart 
          trends={stats.weekly_trends}
          windowDays={stats.window_days}
          maxWindowDays={stats.max_window_days}
        />
        <SeverityChart breakdown={stats.severity_breakdown} />
      </div>

      {/* Regions Table */}
      <RegionsTable regions={stats.top_regions} />
    </div>
  );
}
```

---

## Advanced Features

### 6. Plan Upgrade Prompt

**Show when user hits plan limits**
```tsx
// components/PlanLimitBanner.tsx
export function PlanLimitBanner({ maxWindowDays }: { maxWindowDays: number }) {
  if (maxWindowDays >= 90) return null; // Already on top plan

  const planMap = {
    7: { current: 'FREE', upgrade: 'PRO', days: 30 },
    30: { current: 'PRO', upgrade: 'ENTERPRISE', days: 90 }
  };

  const plan = planMap[maxWindowDays];
  if (!plan) return null;

  return (
    <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
      <div className="flex items-start">
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-100">
            Limited to {maxWindowDays}-day view ({plan.current} Plan)
          </h3>
          <p className="text-sm text-blue-700 dark:text-blue-300 mt-1">
            Upgrade to {plan.upgrade} for {plan.days}-day historical data, advanced analytics, and more.
          </p>
        </div>
        <button className="ml-4 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-lg">
          Upgrade Now
        </button>
      </div>
    </div>
  );
}
```

---

### 7. Export/Download Stats

**CSV or PDF Export**
```tsx
// utils/exportStats.ts
export function exportStatsCSV(stats: any) {
  const rows = [
    ['Metric', 'Value'],
    ['Threats (7d)', stats.threats_7d],
    ['Threats (30d)', stats.threats_30d],
    ['Trend', `${stats.trend_7d}%`],
    ['Active Monitors', stats.active_monitors],
    ['Tracked Locations', stats.tracked_locations],
    ['', ''],
    ['Date', 'Count'],
    ...stats.weekly_trends.map(t => [t.date, t.count]),
    ['', ''],
    ['Severity', 'Count', 'Percentage'],
    ['Critical', stats.severity_breakdown.critical, `${stats.severity_breakdown.critical_pct}%`],
    ['High', stats.severity_breakdown.high, `${stats.severity_breakdown.high_pct}%`],
    ['Medium', stats.severity_breakdown.medium, `${stats.severity_breakdown.medium_pct}%`],
    ['Low', stats.severity_breakdown.low, `${stats.severity_breakdown.low_pct}%`]
  ];

  const csv = rows.map(row => row.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `security-stats-${new Date().toISOString().split('T')[0]}.csv`;
  a.click();
}

// Add to dashboard:
<button onClick={() => exportStatsCSV(stats)} className="...">
  Export CSV
</button>
```

---

### 8. Real-Time Updates with WebSocket

**Optional: Live dashboard updates**
```tsx
// hooks/useRealtimeStats.ts
import { useEffect, useState } from 'react';

export function useRealtimeStats() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    // Polling approach (simpler)
    const interval = setInterval(async () => {
      const res = await fetch('/api/stats/overview', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      const data = await res.json();
      setStats(data);
    }, 30000); // Update every 30s

    return () => clearInterval(interval);
  }, []);

  return stats;
}

// Usage:
const stats = useRealtimeStats();
```

---

## Mobile Responsive Design

### 9. Mobile-Optimized Cards

```tsx
// Mobile-first responsive grid
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
  {/* Cards stack on mobile, 2-col on tablet, 4-col on desktop */}
</div>

// Compact chart on mobile
<div className="h-64 sm:h-80 lg:h-96">
  <Line data={data} options={options} />
</div>
```

---

## TypeScript Interfaces

### 10. Type Definitions

```typescript
// types/stats.ts
export interface StatsOverview {
  ok: boolean;
  updated_at: string;
  threats_7d: number;
  threats_30d: number;
  trend_7d: number;
  active_monitors: number;
  tracked_locations: number;
  chat_messages_month: number;
  window_days: number;
  max_window_days: number;
  weekly_trends: WeeklyTrend[];
  top_regions: Region[];
  severity_breakdown: SeverityBreakdown;
}

export interface WeeklyTrend {
  date: string;
  count: number;
}

export interface Region {
  region: string;
  count: number;
  percentage: number;
}

export interface SeverityBreakdown {
  critical: number;
  high: number;
  medium: number;
  low: number;
  total: number;
  critical_pct: number;
  high_pct: number;
  medium_pct: number;
  low_pct: number;
}
```

---

## Testing

### 11. API Testing with curl

```bash
# Get stats with default window (plan-based)
curl -H "Authorization: Bearer $TOKEN" \
  https://sentinelairss-production.up.railway.app/api/stats/overview

# Request 30-day window (if plan allows)
curl -H "Authorization: Bearer $TOKEN" \
  https://sentinelairss-production.up.railway.app/api/stats/overview?days=30

# Request 90-day window (ENTERPRISE only)
curl -H "Authorization: Bearer $TOKEN" \
  https://sentinelairss-production.up.railway.app/api/stats/overview?days=90
```

---

## Caching Strategy

**Frontend caching with React Query**
```tsx
import { useQuery } from '@tanstack/react-query';

export function useDashboardStats(windowDays = 7) {
  return useQuery({
    queryKey: ['stats', windowDays],
    queryFn: async () => {
      const res = await fetch(`/api/stats/overview?days=${windowDays}`, {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      return res.json();
    },
    staleTime: 2 * 60 * 1000, // 2 minutes (matches backend cache)
    cacheTime: 5 * 60 * 1000,  // 5 minutes
    refetchOnWindowFocus: true
  });
}

// Usage:
const { data: stats, isLoading, error } = useDashboardStats(30);
```

---

## Summary

**What You Can Build:**

1. ✅ **Executive Dashboard** - KPI cards with trends
2. ✅ **Analytics Charts** - Line/donut charts with severity breakdown
3. ✅ **Regional Heatmaps** - Top threat regions with percentages
4. ✅ **Plan-Based Upsells** - Show locked features for FREE users
5. ✅ **Export Reports** - CSV/PDF download for sharing
6. ✅ **Mobile App** - Responsive design for all devices
7. ✅ **Real-Time Updates** - Auto-refresh every 2 minutes
8. ✅ **Historical Trends** - Up to 90 days for ENTERPRISE plans

**Plan Differentiation:**
- **FREE**: 7-day window, basic stats
- **PRO**: 30-day window, advanced analytics
- **ENTERPRISE/VIP**: 90-day window, full historical data

Your updated structure will work seamlessly - just update plan names in `PLAN_FEATURE_LIMITS` when you migrate!
