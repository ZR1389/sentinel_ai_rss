# Plan & Feature Gate API Endpoints

Comprehensive reference for frontend integration with plan management, feature gating, and usage tracking.

**Base URL:** `https://your-backend.up.railway.app`  
**Authentication:** All user endpoints require `Authorization: Bearer <JWT_TOKEN>` header.

---

## Core Plan Management

### 1. Get User Plan Info
**GET** `/api/user/plan`

Returns current plan, trial status, features, and usage snapshot.

**Response:**
```json
{
  "ok": true,
  "plan": "FREE|PRO|BUSINESS|ENTERPRISE",
  "is_trial": false,
  "trial_ends_at": "2025-12-01T00:00:00Z",  // null if not trial
  "features": {
    "chat_messages_monthly": 500,
    "conversation_threads": 50,
    "messages_per_thread": 50,
    "can_archive_threads": true,
    "map_access_days": 30,
    "timeline_access": true
    // ... full feature matrix
  },
  "usage": {
    "chat_messages_monthly_used": 15,
    "chat_messages_monthly_limit": 500,
    "active_threads": 3,
    "threads_limit": 50,
    "archived_threads": 5
  }
}
```

### 2. Upgrade Plan
**POST** `/api/user/upgrade`

Change user plan (records in `plan_changes` table).

**Request:**
```json
{
  "plan": "PRO|BUSINESS|ENTERPRISE"
}
```

**Response:**
```json
{
  "ok": true,
  "message": "Upgraded from FREE to PRO",
  "new_plan": "PRO"
}
```

**Errors:**
- `400` - Invalid plan
- `404` - User missing

---

## Trial Management

### 3. Start Trial
**POST** `/api/user/trial/start`

Start a trial for FREE users (default PRO).

**Request:**
```json
{
  "plan": "PRO|BUSINESS|ENTERPRISE"  // optional, default PRO
}
```

**Response:**
```json
{
  "ok": true,
  "trial_started": true,
  "plan": "PRO",
  "trial_ends_at": "2025-12-08T00:00:00Z"
}
```

**Errors:**
- `400` - Already on trial / not FREE user
- `404` - User missing

### 4. End Trial
**POST** `/api/user/trial/end`

End trial (optionally convert to paid).

**Request:**
```json
{
  "convert_to_paid": true  // optional, default false
}
```

**Response (convert):**
```json
{
  "ok": true,
  "trial_converted": true,
  "plan": "PRO"
}
```

**Response (expire):**
```json
{
  "ok": true,
  "trial_expired": true,
  "plan": "FREE"
}
```

### 5. Trial Status
**GET** `/api/user/trial/status`

Get trial snapshot.

**Response:**
```json
{
  "ok": true,
  "plan": "PRO",
  "is_trial": true,
  "trial_started_at": "2025-11-21T00:00:00Z",
  "trial_ends_at": "2025-12-05T00:00:00Z",
  "can_start_trial": false
}
```

---

## Feature-Gated Endpoints

### 6. Sentinel Chat (Usage Limited)
**POST** `/api/sentinel-chat`

Chat advisory with plan-based quotas:
- **FREE:** 3 lifetime messages (`lifetime_chat_messages`)
- **Paid:** Monthly quota (`chat_messages_monthly`)

**Request:**
```json
{
  "message": "What are the current threats in Kyiv?"
}
```

**Response (success):**
```json
{
  "ok": true,
  "advisory": "Based on recent intelligence...",
  "usage": {
    "used": 2,
    "limit": 3,
    "scope": "lifetime"  // or "monthly" for paid
  },
  "plan": "FREE"
}
```

**Response (quota exceeded):**
```json
{
  "error": "Free tier chat quota reached",
  "feature_locked": true,
  "required_plan": "PRO",
  "usage": {
    "used": 3,
    "limit": 3,
    "scope": "lifetime"
  }
}
// Status: 403
```

### 7. Map Alerts (Historical Window Gating)
**GET** `/api/map-alerts/gated?days=<N>`

Returns alerts with plan-based historical access:
- **FREE:** 2 days max
- **PRO:** 30 days
- **BUSINESS:** 90 days
- **ENTERPRISE:** 365 days

**Response (success):**
```json
{
  "ok": true,
  "items": [...],  // alert rows
  "features": [...],  // GeoJSON features
  "window_days": 30,
  "plan_limit_days": 30,
  "plan": "PRO"
}
```

**Response (window violation):**
```json
{
  "error": "Plan FREE allows up to 2 days",
  "feature_locked": true,
  "required_plan": "PRO"
}
// Status: 403
```

### 8. Travel Risk Assessment (Usage Limited)
**POST** `/api/travel-risk/assess`

Generate travel risk assessment (monthly quota).

**Request:**
```json
{
  "destination": "Kyiv, Ukraine"
}
```

**Response:**
```json
{
  "ok": true,
  "assessment": {
    "destination": "Kyiv, Ukraine",
    "risk_level": "medium",
    "score": 55,
    "factors": ["Political stability moderate", "..."]
  }
}
```

### 9. Timeline Access (Feature Gated)
**GET** `/api/timeline?days=<N>`

Incident timeline (requires `timeline_access` boolean feature).

**Response (denied):**
```json
{
  "error": "Feature timeline_access not available on FREE plan",
  "feature_locked": true,
  "required_plan": "PRO",
  "upgrade_url": "/sentinel-ai#pricing"
}
// Status: 403
```

### 10. Stats Overview (Tiered Dashboard)
**GET** `/api/stats/overview/gated?days=<N>`

Dashboard statistics with plan-based enrichment:
- **PRO:** basic
- **BUSINESS:** advanced (weekly trends, top regions)
- **ENTERPRISE:** custom (proprietary metrics)

**Response:**
```json
{
  "ok": true,
  "threats_7d": 45,
  "trend_7d": "up",
  "weekly_trends": [...],  // advanced+
  "top_regions": [...],    // advanced+
  "custom_metrics": {...}, // enterprise only
  "dashboard_level": "advanced"
}
```

---

## Chat Thread/Conversation Management

**Dual-Limit Model:**
- **Active thread count** (excludes archived/deleted)
- **Per-thread message cap** (hard limit per conversation)
- **Monthly message quota** (global safety valve for paid plans)

### 11. Create Thread
**POST** `/api/chat/threads`

Save a conversation with messages (enforces all three limits).

**Request:**
```json
{
  "title": "Cybersecurity threats in London",
  "investigation_topic": "London financial district security",  // optional
  "messages": [
    {
      "role": "user",
      "content": "What are current threats in London?",
      "timestamp": "2025-11-21T10:30:00Z"
    },
    {
      "role": "assistant", 
      "content": "Based on recent intelligence...",
      "timestamp": "2025-11-21T10:30:15Z"
    }
  ]
}
```

**Response (success):**
```json
{
  "ok": true,
  "thread_id": "uuid-here",
  "created_at": "2025-11-21T10:30:20Z"
}
```

**Response (thread limit reached):**
```json
{
  "error": "Max active threads (5) reached. Delete an old thread or upgrade to PRO.",
  "feature_locked": true,
  "required_plan": "PRO",
  "can_archive": false
}
// Status: 403
```

**Validation Rules:**
1. **Active thread count** < plan limit (excludes archived)
2. **Initial message count** ≤ per-thread limit
3. **Monthly total** + new messages ≤ monthly quota

**Plan Limits:**
- **FREE:** 5 active threads, 3 messages/thread, no archiving
- **PRO:** 50 active threads, 50 messages/thread, 500/month, archiving enabled
- **BUSINESS:** 100 active threads, 100 messages/thread, 1000/month
- **ENTERPRISE:** Unlimited threads/messages, 2500/month soft limit

### 12. List Threads
**GET** `/api/chat/threads?archived=false`

Returns user's conversation threads with usage stats.

**Query Params:**
- `archived=false` (default) - Active threads only
- `archived=true` - Archived threads (PRO+ only)
- `archived=all` - Both active and archived

**Response:**
```json
{
  "ok": true,
  "threads": [
    {
      "thread_id": "uuid-1",
      "title": "Cybersecurity threats in London",
      "investigation_topic": "London financial district security",
      "message_count": 6,
      "is_archived": false,
      "created_at": "2025-11-21T10:30:20Z",
      "updated_at": "2025-11-21T11:45:00Z",
      "last_message_preview": "I recommend implementing..."
    }
  ],
  "total": 3,
  "usage": {
    "active_threads": 3,
    "threads_limit": 5,
    "archived_threads": 0,
    "monthly_messages_used": 15,
    "monthly_messages_limit": null,
    "can_archive": false
  }
}
```

### 13. Get Thread
**GET** `/api/chat/threads/:thread_id`

Retrieve full conversation thread with all messages.

**Response:**
```json
{
  "ok": true,
  "thread": {
    "thread_id": "uuid-1",
    "title": "Cybersecurity threats in London",
    "investigation_topic": "London financial district security",
    "is_archived": false,
    "message_count": 4,
    "messages": [
      {
        "role": "user",
        "content": "What are current threats in London?",
        "timestamp": "2025-11-21T10:30:00Z"
      },
      {
        "role": "assistant",
        "content": "Based on recent intelligence...",
        "timestamp": "2025-11-21T10:30:15Z"
      }
    ],
    "created_at": "2025-11-21T10:30:20Z",
    "updated_at": "2025-11-21T11:45:00Z"
  }
}
```

### 14. Update Thread
**PUT** `/api/chat/threads/:thread_id`

Update thread title/topic or append messages (enforces per-thread and monthly limits).

**Request:**
```json
{
  "title": "Updated title",  // optional
  "investigation_topic": "New focus area",  // optional
  "append_messages": [  // optional
    {
      "role": "user",
      "content": "Follow-up question",
      "timestamp": "2025-11-21T12:00:00Z"
    },
    {
      "role": "assistant",
      "content": "Response to follow-up",
      "timestamp": "2025-11-21T12:00:05Z"
    }
  ]
}
```

**Response (success):**
```json
{
  "ok": true,
  "updated_at": "2025-11-21T12:00:05Z"
}
```

**Response (thread full):**
```json
{
  "error": "Thread message limit (3) reached",
  "feature_locked": true,
  "thread_full": true,
  "required_plan": "PRO"
}
// Status: 403
```

**Use Case (FREE user):**
- Thread has 3 messages → locked
- Save thread and create new one (up to 5 total)
- Or upgrade to PRO for 50 messages/thread

### 15. Delete Thread
**DELETE** `/api/chat/threads/:thread_id`

Remove conversation thread (soft delete).

**Response:**
```json
{
  "ok": true,
  "message": "Thread deleted"
}
```

### 16. Archive Thread (PRO+)
**POST** `/api/chat/threads/:thread_id/archive`

Archive thread (removes from active count, not deleted). **PRO plan or higher required.**

**Response:**
```json
{
  "ok": true,
  "archived_at": "2025-11-21T12:00:00Z",
  "active_threads_remaining": 48
}
```

**Response (FREE user):**
```json
{
  "error": "Archiving requires PRO plan or higher",
  "feature_locked": true,
  "required_plan": "PRO"
}
// Status: 403
```

**Use Case:** Free up active thread slots without losing conversation history.

### 17. Unarchive Thread
**POST** `/api/chat/threads/:thread_id/unarchive`

Restore thread from archive (counts against active limit).

**Response (success):**
```json
{
  "ok": true,
  "unarchived_at": "2025-11-21T12:05:00Z"
}
```

**Response (limit reached):**
```json
{
  "error": "Max active threads (50). Archive another thread first.",
  "feature_locked": true
}
// Status: 403
```

---

## Saved Searches (Plan Limits)

### 16. List Saved Searches
**GET** `/api/monitoring/searches`

Returns user's saved searches with plan limit info.

**Response:**
```json
{
  "ok": true,
  "searches": [
    {
      "id": 1,
      "name": "Ukraine incidents",
      "query": {"region": "Eastern Europe"},
      "alert_enabled": true,
      "alert_frequency": "daily",
      "created_at": "2025-11-01T00:00:00Z"
    }
  ],
  "limit": 3,   // PRO allows 3
  "used": 1,
  "plan": "PRO"
}
```

### 17. Create Saved Search
**POST** `/api/monitoring/searches`

Create search with plan enforcement:
- **FREE:** 0 (disabled)
- **PRO:** 3
- **BUSINESS:** 10
- **ENTERPRISE:** unlimited

**Request:**
```json
{
  "name": "High-threat alerts",
  "query": {"severity": "high"},
  "alert_enabled": true,
  "alert_frequency": "daily"
}
```

**Response (success):**
```json
{
  "ok": true,
  "id": 42
}
```

**Response (limit reached):**
```json
{
  "error": "Max saved searches (3) reached",
  "feature_locked": true,
  "required_plan": "BUSINESS"
}
// Status: 403
```

---

## Alert Export (Format Gating)

### 18. Export Alerts
**POST** `/api/export/alerts`

Export alerts in plan-allowed formats:
- **FREE:** No export
- **PRO:** CSV only
- **BUSINESS+:** All formats (CSV, JSON, PDF)

**Request:**
```json
{
  "format": "csv",
  "alert_ids": [123, 456, 789]
}
```

**Response:**
```json
{
  "ok": true,
  "download_url": "/downloads/alerts_export_csv_3.dat",
  "format": "csv",
  "plan": "PRO"
}
```

**Errors:**
- `403` - Format not allowed for plan

---

## Internal/Cron Endpoint

### 19. Check Expired Trials (Cron)
**POST** `/api/cron/check-trials`

**Headers:** `X-Cron-Secret: <CRON_SECRET>`

Processes expired trials (converts or downgrades based on payment method).

**Response:**
```json
{
  "ok": true,
  "expired_trials": 5
}
```

**Usage:** Schedule daily via external cron:
```bash
curl -X POST https://your-backend/api/cron/check-trials \
  -H "X-Cron-Secret: $CRON_SECRET"
```

---

## Plan Feature Matrix Summary

| Feature                      | FREE | PRO | BUSINESS | ENTERPRISE |
|------------------------------|------|-----|----------|------------|
| Chat (lifetime/monthly)      | 3    | 500 | 1000     | 2500       |
| Conversation threads (active)| 5    | 50  | 100      | unlimited  |
| Messages per thread          | 3    | 50  | 100      | unlimited  |
| Thread archiving             | ❌   | ✅  | ✅       | ✅         |
| Map historical access (days) | 2    | 30  | 90       | 365        |
| Timeline access              | ❌   | ✅  | ✅       | ✅         |
| Statistics dashboard         | ❌   | basic | advanced | custom    |
| Saved searches               | 0    | 3   | 10       | unlimited  |
| Alert export                 | ❌   | CSV | All      | All        |
| Travel assessments           | 1 lifetime | unlimited | unlimited | unlimited |
| Trial duration               | -    | 7d  | 7d       | 14d        |

---

## Frontend Integration Notes

### Auth Pattern
All endpoints expect JWT in `Authorization: Bearer <token>` header. Use existing auth flow.

### Error Handling
Feature-locked responses (`403`) include:
```json
{
  "error": "Human-readable message",
  "feature_locked": true,
  "required_plan": "PRO",
  "upgrade_url": "/sentinel-ai#pricing"  // optional
}
```

**Suggested UI:** Show upgrade CTA with plan recommendation.

### Usage Display
For quota-based features (chat, saved searches), display:
- Current usage (`used`)
- Limit (`limit`)
- Progress bar
- Upgrade prompt when approaching limit

### Plan Metadata Caching
Call `/api/user/plan` on login to cache feature matrix in frontend state. Refresh after upgrade/trial start.

### Testing
Use test tokens for each plan tier:
```bash
FREE_USER_TOKEN="eyJ..."
PRO_USER_TOKEN="eyJ..."
BUSINESS_USER_TOKEN="eyJ..."
```

See `API_PLAN_ENDPOINTS.md` for curl examples.

---

## Environment Variables

Backend requires:
- `CRON_SECRET` - Secret for trial expiration cron endpoint
- `DATABASE_URL` - PostgreSQL connection string
- `STRIPE_SECRET_KEY` - (Optional) For payment method checks

---

## Database Schema Reference

New tables supporting plan system:
- `feature_usage` - Monthly usage tracking
- `saved_searches` - User search configurations
- `trip_plans` - Travel planning (future)
- `plan_changes` - Audit log of plan transitions
- `chat_threads` - Conversation threads (thread_uuid, is_archived, message_count)
- `chat_messages` - Thread messages (role, content, timestamp)

Users table additions:
- `lifetime_chat_messages`, `lifetime_map_views`, `lifetime_travel_assessments`
- `is_trial`, `trial_started_at`, `trial_ends_at`
- `stripe_customer_id`, `stripe_subscription_id`

PL/pgSQL functions:
- `increment_feature_usage(user_id, feature)` - Atomic usage increment
- `check_feature_limit(user_id, feature)` - Quota validation
- `check_thread_limit(user_id, plan)` - Active thread validation (excludes archived)
- `check_thread_message_limit(thread_id, plan)` - Per-thread message cap
- `get_monthly_message_count(user_id)` - Global monthly quota tracking

Views:
- `user_active_threads` - Aggregates active/archived thread counts per user

Triggers:
- `thread_message_added` → `update_thread_stats()` - Auto-updates message_count on chat_messages insert

---

**Last Updated:** November 21, 2025  
**API Version:** v1.0  
**Backend:** Railway deployment
