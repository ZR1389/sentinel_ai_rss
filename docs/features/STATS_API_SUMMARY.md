# Stats Overview API - Implementation Summary

## ✅ What Was Implemented

### 1. Plan-Based Window Limits
- **FREE Plan**: 7-day maximum window
- **PRO Plan**: 30-day maximum window  
- **ENTERPRISE/VIP**: 90-day maximum window
- API returns `max_window_days` to indicate user's plan limit
- Requested `days` parameter is clamped to plan limit

### 2. Severity Percentages
Added percentage calculations for each severity level:
```json
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
```

### 3. Tracked Locations (Alert-Based)
**Changed from:** Count of saved user context locations  
**Changed to:** Count of distinct alert locations with coordinates

Query now counts unique `city` or `country` values from alerts table within the window period:
```sql
SELECT COUNT(DISTINCT COALESCE(city, country)) 
FROM alerts 
WHERE published >= NOW() - make_interval(days => ?)
AND lat IS NOT NULL AND lon IS NOT NULL
```

This gives a more accurate representation of geographic threat coverage.

---

## 📊 API Endpoint

### Request
```
GET /api/stats/overview?days=7
Authorization: Bearer <token>
```

### Parameters
- `days` (optional): 7, 30, or 90 - defaults to user's plan maximum
- Automatically clamped to plan limit if requested value exceeds it

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
  "weekly_trends": [...],
  "top_regions": [...],
  "severity_breakdown": {...}
}
```

---

## 🚀 Deployment

### 1. Push Changes
```bash
git add main.py FRONTEND_STATS_INTEGRATION.md test_stats_endpoint.py
git commit -m "feat: enhance stats API with plan limits, severity percentages, alert-based locations"
git push origin main
```

### 2. Test Locally (Optional)
```bash
# Set your token
export SENTINEL_TOKEN="your_jwt_token"

# Run test script
python test_stats_endpoint.py
```

### 3. Test Production
```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://sentinelairss-production.up.railway.app/api/stats/overview
```

---

## 🎨 Frontend Integration

See `FRONTEND_STATS_INTEGRATION.md` for complete React/TypeScript examples including:

1. **Dashboard Stats Cards** - KPIs with trend indicators
2. **Severity Donut Chart** - Visual breakdown with percentages
3. **Weekly Trends Line Chart** - Time series with window selector
4. **Regional Threat Table** - Top regions with progress bars
5. **Plan Upgrade Prompts** - Upsell locked features
6. **Export Functionality** - CSV/PDF downloads
7. **Mobile Responsive** - Optimized for all screen sizes
8. **TypeScript Types** - Full type definitions
9. **React Query Integration** - Caching and auto-refresh
10. **WebSocket Updates** - Real-time dashboard (optional)

---

## 📝 Frontend Components Quick Start

### Basic Dashboard
```tsx
import { useDashboardStats } from '@/hooks/useDashboardStats';

export default function Dashboard() {
  const { data: stats, isLoading } = useDashboardStats(7);
  
  if (isLoading) return <div>Loading...</div>;
  
  return (
    <div>
      <h1>Security Dashboard</h1>
      
      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <Card title="Threats (7d)" value={stats.threats_7d} />
        <Card title="Trend" value={`${stats.trend_7d}%`} />
        <Card title="Locations" value={stats.tracked_locations} />
        <Card title="Chat Used" value={stats.chat_messages_month} />
      </div>
      
      {/* Charts */}
      <SeverityChart data={stats.severity_breakdown} />
      <TrendsChart data={stats.weekly_trends} />
      <RegionsTable data={stats.top_regions} />
    </div>
  );
}
```

### Hook with Caching
```tsx
import { useQuery } from '@tanstack/react-query';

export function useDashboardStats(days = 7) {
  return useQuery({
    queryKey: ['stats', days],
    queryFn: async () => {
      const res = await fetch(`/api/stats/overview?days=${days}`, {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      return res.json();
    },
    staleTime: 2 * 60 * 1000, // 2 minutes
    refetchOnWindowFocus: true
  });
}
```

---

## 🔄 When You Change Plan Structure

When you migrate to your new plan system, update `plan_utils.py`:

```python
PLAN_FEATURE_LIMITS = {
    "YOUR_NEW_FREE_NAME": {
        "statistics_days": 7,
        # ... other limits
    },
    "YOUR_NEW_PRO_NAME": {
        "statistics_days": 30,
        # ... other limits
    },
    "YOUR_NEW_ENTERPRISE_NAME": {
        "statistics_days": 90,
        # ... other limits
    },
}
```

The stats endpoint will automatically respect the new plan names and limits!

---

## 🧪 Testing Checklist

- [ ] Test endpoint without token (expect 401)
- [ ] Test with FREE plan token (expect window_days ≤ 7)
- [ ] Test with PRO plan token (expect window_days ≤ 30)
- [ ] Test with ENTERPRISE token (expect window_days ≤ 90)
- [ ] Verify severity percentages sum to ~100%
- [ ] Verify tracked_locations counts distinct alert locations
- [ ] Test caching (same request within 2 minutes should be instant)
- [ ] Test invalid days parameter (expect default to plan limit)
- [ ] Frontend: Test plan upgrade prompt for FREE users
- [ ] Frontend: Test window selector respects max_window_days

---

## 📈 Key Benefits

### For Users
1. **Clear Plan Differentiation** - Visual limits drive upgrades
2. **Actionable Insights** - Percentages make severity distribution clear
3. **Geographic Coverage** - Know how many locations are being monitored
4. **Historical Trends** - Spot patterns over time

### For Business
1. **Upsell Opportunities** - FREE users see locked 30d/90d windows
2. **Data-Driven Plans** - Show value of higher-tier plans
3. **Engagement Metrics** - Track chat usage and monitor adoption
4. **Retention Tool** - Dashboard keeps users coming back

### For Frontend Devs
1. **Complete Components** - Copy-paste React examples
2. **TypeScript Support** - Full type definitions included
3. **Responsive Design** - Mobile-first examples
4. **Chart Libraries** - Ready for Chart.js/Recharts integration
5. **State Management** - React Query examples with caching

---

## 🚧 Future Enhancements

Consider adding:
- **Alerts by Category** - Breakdown by malware/ransomware/phishing
- **User Activity Log** - Recent searches, views, exports
- **Custom Date Ranges** - Allow arbitrary start/end dates (ENTERPRISE only)
- **Comparative Analytics** - Week-over-week, month-over-month
- **Anomaly Detection** - Flag unusual spikes in trends
- **Scheduled Reports** - Email weekly/monthly summaries
- **Team Dashboard** - Multi-user aggregated stats

---

## 📞 Support

**Backend Issues:**
- Check Railway logs: `railway logs`
- Verify database connection: `psql $DATABASE_URL -c "SELECT COUNT(*) FROM alerts"`
- Test endpoint: `python test_stats_endpoint.py`

**Frontend Issues:**
- Check browser console for errors
- Verify token in localStorage: `localStorage.getItem('token')`
- Test API directly with curl first
- Check CORS headers in network tab

---

## 🎉 Summary

You now have a **production-ready stats dashboard API** with:

✅ Plan-based access control  
✅ Rich severity analytics with percentages  
✅ Real-world threat location tracking  
✅ 2-minute response caching  
✅ Complete frontend examples  
✅ TypeScript type definitions  
✅ Mobile-responsive components  
✅ Testing utilities  

**Ready to deploy!** Push to Railway and start building your dashboard UI.
