# Frontend Integration Guide - Plan-Based Feature Access

**Date**: November 15, 2025  
**Backend Status**: ✅ Ready to Deploy  
**Breaking Changes**: Yes - See Migration section

---

## 🎯 Overview

All users must login/signup to access features. Upon registration, users receive a **FREE** plan with 7-day data access and 3 chat messages. Upgrading unlocks extended history and higher quotas.

---

## 📋 Plan Structure

### Confirmed Plan Names:
- **FREE** (default for new signups)
- **PRO** (paid tier 1)
- **ENTERPRISE** (paid tier 2)

### Plan Limits:

| Feature | FREE | PRO | ENTERPRISE |
|---------|------|-----|------------|
| **Chat Messages/Month** | 3 | 1,000 | 5,000 |
| **Data History Window** | 7 days | 30 days | 90 days |
| **Max Alerts per Query** | 30 | 100 | 500 |
| **Map Access** | 7-day data | 30-day data | 90-day data |
| **Timeline Access** | 7-day data | 30-day data | 90-day data |
| **Statistics Access** | 7-day data | 30-day data | 90-day data |
| **Monitoring Access** | 7-day data | 30-day data | 90-day data |
| **Email Verification** | Required | Required | Required |

---

## 🔐 Access Control

### Protected Pages (Login Required):
- `/map` - Global threat map
- `/travel-risk-map` - Travel risk assessment map
- `/timeline` - Alert timeline view
- `/statistics` - Threat statistics dashboard
- `/monitoring` - Coverage monitoring
- `/sentinel-ai-chat` - AI chat interface
- `/dashboard` - User dashboard
- `/account` - Account settings
- `/alerts` - Alert list view

### Public Pages (No Auth):
- Homepage (`/`)
- Marketing pages (`/about`, `/contact`, `/pricing`, `/faq`)
- Blog pages
- Service pages (executive-protection, risk-advisory, etc.)

---

## 🔄 API Response Changes

### 1. `/auth/status` - **NEW FORMAT**

**Endpoint**: `GET /auth/status`  
**Headers**: `Authorization: Bearer <token>`

**Response**:
```json
{
  "email": "user@example.com",
  "plan": "FREE",
  "email_verified": true,
  "usage": {
    "chat_messages_used": 2,
    "chat_messages_limit": 3
  },
  "limits": {
    "alerts_days": 7,
    "alerts_max_results": 30,
    "map_days": 7,
    "timeline_days": 7,
    "statistics_days": 7,
    "monitoring_days": 7
  }
}
```

**PRO User Example**:
```json
{
  "email": "pro@example.com",
  "plan": "PRO",
  "email_verified": true,
  "usage": {
    "chat_messages_used": 50,
    "chat_messages_limit": 1000
  },
  "limits": {
    "alerts_days": 30,
    "alerts_max_results": 100,
    "map_days": 30,
    "timeline_days": 30,
    "statistics_days": 30,
    "monitoring_days": 30
  }
}
```

---

### 2. `/profile/me` - **NEW FORMAT**

**Endpoint**: `GET /profile/me`  
**Headers**: `Authorization: Bearer <token>`

**Response**:
```json
{
  "ok": true,
  "user": {
    "email": "user@example.com",
    "plan": "FREE",
    "email_verified": true,
    "name": "John Doe",
    "employer": "Acme Corp",
    "usage": {
      "chat_messages_used": 2,
      "chat_messages_limit": 3
    },
    "limits": {
      "alerts_days": 7,
      "alerts_max_results": 30,
      "map_days": 7,
      "timeline_days": 7,
      "statistics_days": 7,
      "monitoring_days": 7
    },
    "used": 2,
    "limit": 3
  }
}
```

**Notes**:
- `user.used` and `user.limit` are kept for backward compatibility
- `user.limits` is the new canonical source for feature access windows

---

### 3. `/alerts/latest` - **BEHAVIOR CHANGE**

**Endpoint**: `GET /alerts/latest`  
**Headers**: `Authorization: Bearer <token>`  
**Query Params**: `?lat=47.5&lon=19&radius=200&days=30&limit=100`

**OLD Behavior**:
- ❌ FREE users got 403 Forbidden
- ✅ Only PRO/ENTERPRISE could access

**NEW Behavior**:
- ✅ ALL authenticated users can access
- Server automatically caps `days` and `limit` to user's plan
- FREE user requesting `?days=30&limit=100` gets max 7 days, 30 results
- PRO user with same query gets full 30 days, 100 results

**Response** (GeoJSON format):
```json
{
  "ok": true,
  "items": [
    {
      "uuid": "abc-123",
      "title": "Security Alert in Lagos",
      "published": "2025-11-15T10:30:00Z",
      "country": "Nigeria",
      "city": "Lagos",
      "score": 75,
      "threat_level": "high",
      "latitude": 6.5244,
      "longitude": 3.3792
    }
  ],
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [3.3792, 6.5244]
      },
      "properties": {
        "uuid": "abc-123",
        "title": "Security Alert in Lagos",
        "score": 75,
        "threat_level": "high",
        "country": "Nigeria",
        "city": "Lagos"
      }
    }
  ]
}
```

---

### 4. `/chat` or `/api/sentinel-chat` - **QUOTA HANDLING**

**Success Response** (202 or 200):
```json
{
  "session_id": "uuid-abc-123",
  "accepted": true,
  "quota": {
    "used": 3,
    "limit": 3,
    "plan": "FREE"
  }
}
```

**Quota Exceeded Response** (403):
```json
{
  "code": "QUOTA_EXCEEDED",
  "error": "Monthly chat quota reached for your plan.",
  "quota": {
    "used": 3,
    "limit": 3,
    "plan": "FREE"
  }
}
```

---

## 🎨 Frontend Implementation

### 1. Update Auth Context

```javascript
// contexts/AuthContext.js
const [auth, setAuth] = useState({
  token: null,
  user: null,
  plan: 'FREE',
  quota: { used: 0, limit: 3 },
  limits: {
    alerts_days: 7,
    alerts_max_results: 30,
    map_days: 7,
    timeline_days: 7,
    statistics_days: 7,
    monitoring_days: 7,
  }
});

// After login or /auth/status call
const fetchAuthStatus = async () => {
  const response = await fetch('/api/auth/status', {
    headers: { Authorization: `Bearer ${token}` }
  });
  const data = await response.json();
  
  setAuth({
    ...auth,
    plan: data.plan,
    quota: { 
      used: data.usage.chat_messages_used, 
      limit: data.usage.chat_messages_limit 
    },
    limits: data.limits  // NEW: Store feature limits
  });
};
```

---

### 2. Display Plan Limits in UI

```javascript
// components/PlanBanner.js
import { useAuth } from '@/contexts/AuthContext';

export default function PlanBanner({ feature }) {
  const { auth } = useAuth();
  const days = auth.limits?.[`${feature}_days`] || 7;
  const isPaid = auth.plan !== 'FREE';

  return (
    <div className="plan-banner">
      <span>Viewing last {days} days of data</span>
      {!isPaid && (
        <button onClick={() => router.push('/pricing')}>
          Upgrade to PRO for 30-day access
        </button>
      )}
    </div>
  );
}

// Usage in Map page
<PlanBanner feature="map" />
```

---

### 3. Chat Quota Display

```javascript
// components/ChatQuotaDisplay.js
import { useAuth } from '@/contexts/AuthContext';

export default function ChatQuotaDisplay() {
  const { auth } = useAuth();
  const { used, limit } = auth.quota;
  const percentage = (used / limit) * 100;

  return (
    <div className="quota-display">
      <div className="quota-bar">
        <div 
          className="quota-fill" 
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span>{used} / {limit} messages used</span>
      {used >= limit && (
        <div className="upgrade-cta">
          <p>You've reached your message limit</p>
          <button onClick={() => router.push('/pricing')}>
            Upgrade to {auth.plan === 'FREE' ? 'PRO' : 'ENTERPRISE'}
          </button>
        </div>
      )}
    </div>
  );
}
```

---

### 4. Map Component with Plan-Aware Fetching

```javascript
// components/ThreatMap.js
import { useAuth } from '@/contexts/AuthContext';

export default function ThreatMap() {
  const { auth } = useAuth();
  const [alerts, setAlerts] = useState([]);

  const fetchAlerts = async () => {
    const token = localStorage.getItem('auth_token');
    
    // Request what you want, backend will cap to plan limits
    const response = await fetch(
      `/api/map-alerts?lat=47.5&lon=19&radius=200&days=30&limit=100`,
      {
        headers: { Authorization: `Bearer ${token}` }
      }
    );
    
    const data = await response.json();
    setAlerts(data.features || []);
  };

  return (
    <>
      <PlanBanner feature="map" />
      <MapGL markers={alerts} />
    </>
  );
}
```

---

### 5. Handle Chat Quota Exceeded

```javascript
// pages/sentinel-ai-chat.js
const handleSendMessage = async (message) => {
  try {
    const response = await fetch('/api/sentinel-chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify({ message })
    });

    if (response.status === 403) {
      const error = await response.json();
      if (error.code === 'QUOTA_EXCEEDED') {
        // Update quota from response
        setAuth(prev => ({
          ...prev,
          quota: error.quota
        }));
        
        // Show upgrade modal
        setShowUpgradeModal(true);
        return;
      }
    }

    const data = await response.json();
    // Update quota on success
    if (data.quota) {
      setAuth(prev => ({
        ...prev,
        quota: data.quota
      }));
    }
  } catch (error) {
    console.error('Chat error:', error);
  }
};
```

---

## 🔧 Required Frontend Changes

### High Priority (Breaking):
1. ✅ **Update Auth Context** to store `limits` object from `/auth/status`
2. ✅ **Update Quota Display** to use `usage.chat_messages_limit` instead of hardcoded values
3. ✅ **Remove 403 handling** for FREE users on `/alerts/latest` (now returns data)

### Medium Priority (UX):
4. ✅ **Add Plan Banners** to Map, Timeline, Statistics, Monitoring pages
5. ✅ **Add Upgrade CTAs** when users hit FREE limits (chat quota, data window)
6. ✅ **Update Map/Timeline/Stats** to show actual data window (7/30/90 days)

### Low Priority (Optional):
7. ⚪ **Add plan comparison** on dashboard/account page
8. ⚪ **Show "upgrade to unlock" tooltips** on FREE plan features
9. ⚪ **Add usage analytics** tracking (when users hit limits)

---

## 🧪 Testing Guide

### Test as FREE User:

```bash
# 1. Register new account
POST /auth/register
{
  "email": "test-free@example.com",
  "password": "Test1234!",
  "name": "Free User"
}

# 2. Login and get token
POST /auth/login
{
  "email": "test-free@example.com",
  "password": "Test1234!"
}

# 3. Check auth status
GET /auth/status
Headers: { Authorization: Bearer <token> }

# Expected:
{
  "plan": "FREE",
  "usage": { "chat_messages_used": 0, "chat_messages_limit": 3 },
  "limits": { "map_days": 7, "alerts_max_results": 30, ... }
}

# 4. Fetch map data
GET /alerts/latest?days=30&limit=100
Headers: { Authorization: Bearer <token> }

# Expected: Returns max 7 days, 30 results (silently capped)

# 5. Send 3 chat messages
POST /api/sentinel-chat (x3)

# 6. Send 4th chat message
POST /api/sentinel-chat

# Expected: 403 with code "QUOTA_EXCEEDED"
```

### Test as PRO User:

```bash
# 1. Upgrade account to PRO (via admin or payment flow)

# 2. Check auth status
GET /auth/status

# Expected:
{
  "plan": "PRO",
  "usage": { "chat_messages_used": X, "chat_messages_limit": 1000 },
  "limits": { "map_days": 30, "alerts_max_results": 100, ... }
}

# 3. Fetch map data with full params
GET /alerts/latest?days=30&limit=100

# Expected: Returns full 30 days, 100 results
```

---

## 🚨 Breaking Changes & Migration

### What Changed:

1. **`/auth/status` Response**:
   - ✅ Added: `limits` object with feature access windows
   - ✅ Kept: `usage` object (backward compatible)

2. **`/profile/me` Response**:
   - ✅ Added: `user.limits` object
   - ✅ Kept: `user.used` and `user.limit` (backward compatible)

3. **`/alerts/latest` Behavior**:
   - ❌ Removed: 403 error for FREE users
   - ✅ Changed: Now returns data with plan-based caps
   - ⚠️ Frontend should NOT rely on 403 to block FREE users

### Migration Steps:

```javascript
// Before (OLD CODE):
const quota = {
  used: authData.usage?.chat_messages_used || 0,
  limit: authData.plan === 'PRO' ? 1000 : 3  // Hardcoded fallback
};

// After (NEW CODE):
const quota = {
  used: authData.usage?.chat_messages_used || 0,
  limit: authData.usage?.chat_messages_limit || 3  // From backend
};

// NEW: Access feature limits
const mapDays = authData.limits?.map_days || 7;
const alertsMax = authData.limits?.alerts_max_results || 30;
```

---

## 📊 Pricing Page Recommendations

### Suggested Pricing Structure:

| Feature | FREE | PRO | ENTERPRISE |
|---------|------|-----|------------|
| **Monthly Price** | $0 | $49/mo | $199/mo |
| **Chat Messages** | 3 | 1,000 | 5,000 |
| **Data History** | 7 days | 30 days | 90 days |
| **Map Alerts** | 30/query | 100/query | 500/query |
| **Real-time Updates** | ❌ | ✅ | ✅ |
| **Email Alerts** | ❌ | ✅ | ✅ |
| **PDF Reports** | ❌ | ✅ | ✅ |
| **API Access** | ❌ | ❌ | ✅ |
| **Priority Support** | ❌ | ❌ | ✅ |

### Value Propositions:

**FREE Plan**:
- "Try Sentinel AI with 7 days of threat intelligence"
- "Perfect for occasional travelers"
- "No credit card required"

**PRO Plan**:
- "30-day historical data for travel planning"
- "1,000 AI chat messages for detailed analysis"
- "Email and push notifications"

**ENTERPRISE Plan**:
- "90-day intelligence archive"
- "High-volume chat access (5,000 messages)"
- "Priority support and custom integrations"

---

## 🌐 Environment Variables

### Frontend (.env.local for dev):
```bash
NEXT_PUBLIC_API_URL=http://localhost:8080
NEXT_PUBLIC_ENV=development
```

### Frontend (.env.production for Vercel):
```bash
NEXT_PUBLIC_API_URL=https://sentinelairss-production.up.railway.app
NEXT_PUBLIC_ENV=production
```

### Backend (Railway - Already Set):
```bash
DATABASE_URL=postgresql://...
PAID_PLANS=PRO,ENTERPRISE
DEFAULT_PLAN=FREE
```

---

## 📞 Support & Troubleshooting

### Common Issues:

**Issue**: Maps still show 403 errors  
**Solution**: Ensure frontend sends `Authorization: Bearer <token>` header

**Issue**: FREE users see "upgrade required" instead of limited data  
**Solution**: Remove frontend plan checks, let backend enforce caps

**Issue**: Quota shows 0/3 for PRO users  
**Solution**: Check `/auth/status` returns correct `usage.chat_messages_limit`

**Issue**: Users can request 90 days on FREE plan  
**Solution**: This is OK - backend silently caps to 7 days

### Debug Endpoints:

```bash
# Check user's current plan and limits
GET /api/debug-quota
Headers: { Authorization: Bearer <token> }

# Returns full backend state for debugging
```

---

## ✅ Deployment Checklist

### Backend (Ready to Deploy):
- ✅ Plan limits defined in `plan_utils.py`
- ✅ `/auth/status` returns `limits` object
- ✅ `/profile/me` returns `limits` object
- ✅ `/alerts/latest` enforces plan caps
- ✅ Chat quota returns updated quota on success/failure
- ✅ GeoJSON format in `/alerts/latest`

### Frontend (Action Required):
- ⏳ Update `AuthContext` to store `limits`
- ⏳ Update quota display components
- ⏳ Add plan banners to Map/Timeline/Statistics
- ⏳ Add upgrade CTAs on quota exceeded
- ⏳ Test all protected pages with FREE/PRO users
- ⏳ Update environment variables
- ⏳ Deploy to Vercel

---

## 🚀 Ready to Push

**Backend**: Ready for Railway deployment  
**Frontend**: Needs updates per this guide  
**Database**: No schema changes required (uses existing `users.plan` and `user_usage`)

**Next Steps**:
1. Backend team: Push to Railway
2. Frontend team: Implement changes per this guide
3. QA: Test with FREE and PRO accounts
4. Deploy frontend to Vercel
5. Monitor for any issues

---

**Questions or Issues?**  
Reference this guide and check `/api/debug-quota` for live diagnostics.

