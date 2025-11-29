# Plan Limits Alignment (Backend ↔ Frontend)

**Source of Truth:** `config/plans.py` + `plan_utils.py`

## Chat Messages

| Tier | Backend (`chat_messages_monthly`) | Frontend Expectation | Status |
|------|-----------------------------------|---------------------|--------|
| FREE | **0/month, 3 lifetime** | 3 | ⚠️ MISMATCH (lifetime vs monthly) |
| PRO | 500/month | 500 | ✅ MATCH |
| BUSINESS | 1000/month | 1000 | ✅ MATCH |
| ENTERPRISE | 2500/month | 2500 | ✅ MATCH |

**Issue:** FREE tier has `chat_messages_monthly: 0` + `chat_messages_lifetime: 3` but frontend shows "3" without clarifying it's lifetime limit.

---

## Data Access Windows (Historical Data)

| Tier | Backend (`map_access_days`) | Frontend Expectation | Status |
|------|------------------------------|---------------------|--------|
| FREE | **2 days** | 48hr (2d) | ✅ MATCH |
| PRO | 30 days | 30d | ✅ MATCH |
| BUSINESS | **90 days** | 90d | ✅ MATCH |
| ENTERPRISE | **365 days** | 365d | ✅ MATCH |

**Note:** `plan_utils.py` fallback was just fixed (BUSINESS was falling through to FREE=7d, now correctly maps to 60d in legacy adapter, but `plans.py` has 90d).

**❌ CONFLICT:** `plan_utils.py` fallback says BUSINESS=60d, but `plans.py` (source of truth) says 90d!

---

## Thread Limits

| Tier | Backend (`conversation_threads`) | Frontend Expectation | Status |
|------|----------------------------------|---------------------|--------|
| FREE | 5 | 5 | ✅ MATCH |
| PRO | 50 | 50 | ✅ MATCH |
| BUSINESS | 100 | 100 | ✅ MATCH |
| ENTERPRISE | **null (unlimited)** | unlimited | ✅ MATCH |

---

## Messages Per Thread

| Tier | Backend (`messages_per_thread`) | Frontend Expectation | Status |
|------|----------------------------------|---------------------|--------|
| FREE | 3 | 3 | ✅ MATCH |
| PRO | 50 | 50 | ✅ MATCH |
| BUSINESS | 100 | 100 | ✅ MATCH |
| ENTERPRISE | **null (unlimited)** | unlimited | ✅ MATCH |

---

## Trip Planner (Destinations)

| Tier | Backend (`trip_planner_destinations`) | Frontend Expectation | Status |
|------|---------------------------------------|---------------------|--------|
| FREE | **0** | (not shown) | ✅ MATCH |
| PRO | **5** | 5 destinations | ✅ MATCH |
| BUSINESS | **10** | 10 destinations | ✅ MATCH |
| ENTERPRISE | **null (unlimited)** | unlimited | ✅ MATCH |

---

## Alerts & Monitoring

| Feature | FREE | PRO | BUSINESS | ENTERPRISE | Status |
|---------|------|-----|----------|------------|--------|
| `email_alerts` | false | **true** | true | true | ✅ Backend defined |
| `sms_alerts` | false | false | **true** | true | ✅ Backend defined |
| `geofenced_alerts` | false | false | **true** | true | ✅ Backend defined |
| `saved_searches` | 0 | **3** | **10** | unlimited | ✅ Backend defined |

**Frontend "3 active alerts (PRO)" / "10 monitors (BUSINESS)"** → Maps to `saved_searches` limit.

---

## Timeline Access

| Tier | `timeline_days` Backend | Frontend Expectation | Status |
|------|-------------------------|---------------------|--------|
| FREE | 0 (no access) | - | ✅ |
| PRO | 30 | 30d | ✅ |
| BUSINESS | 90 | 90d | ✅ |
| ENTERPRISE | 365 | 365d | ✅ |

---

## Critical Issues to Fix

### 1. BUSINESS `map_access_days` Conflict
- **`plans.py`**: 90 days (source of truth)
- **`plan_utils.py` fallback**: 60 days (just committed)

**Action:** Update `plan_utils.py` fallback to match `plans.py` → 90 days.

### 2. FREE Chat Messages Display
- Backend has **lifetime limit of 3**, not monthly.
- Frontend should show: "3 messages (lifetime)" instead of "3/month".
- **Action:** Clarify in frontend copy or expose `chat_messages_lifetime` field.

---

## Recommended Frontend Changes

### Update Chat Message Display
```diff
- FREE: 3/month
+ FREE: 3 messages (lifetime)
```

### Use Backend Feature Fields
Expose these in `/auth/status` response:
```json
{
  "limits": {
    "chat_messages_monthly": 0,
    "chat_messages_lifetime": 3,
    "conversation_threads": 5,
    "messages_per_thread": 3,
    "trip_planner_destinations": 0,
    "saved_searches": 0,
    "map_access_days": 2,
    "timeline_days": 0
  },
  "features": {
    "email_alerts": false,
    "sms_alerts": false,
    "geofenced_alerts": false,
    "route_analysis": false,
    "briefing_packages": false
  }
}
```

---

## Backend Corrections Needed

1. **Fix `plan_utils.py` BUSINESS tier to 90d** (currently 60d in fallback).
2. **Expose `plans.py` features in `/auth/status`** so frontend can display accurate tier-gated UI.

---

## Summary Table (Corrected)

| Feature | FREE | PRO | BUSINESS | ENTERPRISE |
|---------|------|-----|----------|------------|
| **Chat messages** | 3 lifetime | 500/mo | 1000/mo | 2500/mo |
| **Threads** | 5 | 50 | 100 | Unlimited |
| **Msgs/thread** | 3 | 50 | 100 | Unlimited |
| **Data window** | 2d | 30d | **90d** | 365d |
| **Timeline** | ❌ | 30d | 90d | 365d |
| **Destinations** | ❌ | 5 | 10 | Unlimited |
| **Saved searches** | ❌ | 3 | 10 | Unlimited |
| **Email alerts** | ❌ | ✅ | ✅ | ✅ |
| **SMS alerts** | ❌ | ❌ | ✅ | ✅ |
| **Geofenced** | ❌ | ❌ | ✅ | ✅ |

---

**Next Steps:**
1. Apply BUSINESS tier fix (90d) to `plan_utils.py`.
2. Extend `/auth/status` to return full `limits` + `features` from `plans.py`.
3. Update frontend to consume structured limits instead of hardcoded values.
