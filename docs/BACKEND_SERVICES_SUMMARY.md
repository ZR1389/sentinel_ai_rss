# SENTINEL AI RSS - BACKEND SERVICES SUMMARY

**Current Date:** December 6, 2025  
**Status:** Production-Ready  
**Total API Endpoints:** 61+  
**Database:** PostgreSQL with PostGIS  
**Authentication:** JWT (Bearer tokens)  
**Rate Limiting:** Per-endpoint customizable limits

---

## 📋 TABLE OF CONTENTS

1. [Core Architecture](#core-architecture)
2. [Authentication Services](#authentication-services)
3. [Travel Risk & Geospatial Intelligence](#travel-risk--geospatial-intelligence)
4. [Chat & Advisory Services](#chat--advisory-services)
5. [Data Ingestion & Processing](#data-ingestion--processing)
6. [User Management](#user-management)
7. [Reporting & Exports](#reporting--exports)
8. [Admin Operations](#admin-operations)
9. [Feature Flags & Plan Gating](#feature-flags--plan-gating)
10. [Database Models](#database-models)
11. [External Integrations](#external-integrations)

---

## 🏗️ CORE ARCHITECTURE

### Technology Stack
- **Framework:** Flask (Python)
- **Database:** PostgreSQL with PostGIS (geographic queries)
- **Caching:** Redis (when available), in-memory fallback
- **LLM Routing:** Multi-provider fallback (Grok → OpenAI → DeepSeek)
- **Authentication:** JWT with refresh tokens
- **Deployment:** Railway (with cron jobs)

### Key Infrastructure
- **Request Compression:** gzip (auto on responses >500 bytes)
- **CORS:** Enabled globally with preflight OPTIONS support
- **Error Handling:** Structured JSON responses with standard codes
- **Logging:** Structured logging with metrics tracking
- **Rate Limiting:** Flask-Limiter with in-memory storage

---

## 🔐 AUTHENTICATION SERVICES

### Endpoints
```
POST   /auth/register              - Create new user account (email/password)
POST   /auth/login                 - Login and receive JWT + refresh token
POST   /auth/refresh               - Get new JWT using refresh token
POST   /auth/verify/send           - Send email verification code
POST   /auth/verify/confirm        - Confirm email with verification code
GET    /auth/status                - Get current logged-in user info
```

### Features
- ✅ Email-password registration
- ✅ JWT-based authentication (exp: 24 hours)
- ✅ Refresh token support (longer lived)
- ✅ Email verification (optional)
- ✅ Bearer token validation on protected routes
- ✅ User context injection into `g.user_id`, `g.user_email`

### Security
- Passwords hashed with bcrypt
- HTTPS enforced (via Railway SSL)
- Tokens validated on every protected request
- Rate limiting: 5 login attempts/min per IP

---

## 🌍 TRAVEL RISK & GEOSPATIAL INTELLIGENCE

### Core Travel Risk Assessment
```
POST   /api/travel-risk/assess     - Unified threat assessment for coordinates
GET    /api/travel-risk/itinerary  - List user's itineraries (with pagination)
POST   /api/travel-risk/itinerary  - Create new itinerary
GET    /api/travel-risk/itinerary/{id}    - Get specific itinerary
PATCH  /api/travel-risk/itinerary/{id}    - Update itinerary (optimistic locking)
DELETE /api/travel-risk/itinerary/{id}    - Delete itinerary (soft or hard)
GET    /api/travel-risk/itinerary/stats   - Get user's itinerary statistics
```

### Route Analysis
```
POST   /api/travel-risk/route-analysis     - Analyze waypoint array for threats
POST   /api/travel-risk/route-corridor     - Analyze point-to-point corridor risk
```

### Data Sources
- **GDELT:** Global conflict events (daily updates)
- **RSS Alerts:** Custom threat feeds (processed via NLP)
- **ACLED:** Armed Conflict Location & Event Data
- **SOCMINT:** Social media threat signals
- **Local Database:** Historical threat patterns

### Features
- ✅ Real-time threat fusion from 4+ sources
- ✅ LLM-powered advisory generation (tactical recommendations)
- ✅ Geofenced alert monitoring along routes
- ✅ Optimistic concurrency control (ETag/If-Match headers)
- ✅ Pagination support for itinerary lists
- ✅ Caching (Redis + memory) for repeated queries

### Risk Levels
- `LOW` - Minimal threats detected
- `MODERATE` - Scattered incidents, manageable risk
- `HIGH` - Significant threat activity, caution recommended
- `SEVERE` - Major threats, strong warnings
- `EXTREME` - Critical situation, immediate warnings

### Gating
- **FREE:** /api/travel-risk/assess (limited to 5/day)
- **PRO:** Unlimited assessments + itinerary CRUD
- **BUSINESS:** Route analysis + corridor analysis

---

## 💬 CHAT & ADVISORY SERVICES

### Chat Endpoints
```
POST   /chat                       - Submit query for security advisory
GET    /chat/history               - Get conversation history
POST   /chat/feedback               - Submit feedback on advisor quality
```

### Features
- ✅ Multi-turn conversation support
- ✅ Context awareness (location, recent threats, etc.)
- ✅ Tactical security recommendations
- ✅ LLM provider fallback routing
- ✅ Usage tracking per plan

### LLM Provider Priority
1. 🥇 **Grok (XAI)** - Fastest paid provider
2. 🥈 **OpenAI (GPT-4)** - Reliable paid provider
3. 🥉 **Moonshot** - Slower paid provider
4. 🆓 **DeepSeek** - Free fallback (last resort)

### Rate Limiting
- FREE: 10 chats/day
- PRO: 100 chats/day
- BUSINESS: Unlimited

### Metering
- ✅ Only successful advisories count toward plan usage
- ✅ Refunded if advisory generation fails
- ✅ Does NOT count: health checks, failed requests

---

## 📥 DATA INGESTION & PROCESSING

### RSS Feed Processing
```
POST   /rss/run                    - Manually trigger RSS ingestion
POST   /rss/subscribe              - Subscribe to custom RSS feed
GET    /rss/feeds                  - List active feeds
```

### Threat Engine
```
POST   /engine/run                 - Manually run threat analysis
GET    /engine/status              - Get last processing timestamp
```

### Background Jobs
- **Scheduled:** Railway cron jobs (not in web process)
- **Daily:** Location quality monitoring (7am UTC)
- **Hourly:** RSS feed ingestion
- **Weekly:** Newsletter generation + digest distribution

### Processing Pipeline
1. **Ingestion** - Fetch from RSS, GDELT, ACLED
2. **Normalization** - Standardize fields, validate data
3. **Enrichment** - NLP extraction (entities, locations, sentiment)
4. **Threat Scoring** - Assign severity + risk levels
5. **Deduplication** - Merge events from multiple sources
6. **Storage** - Persist to alerts table
7. **Notification** - Alert users (email/push/webhook)

### Features
- ✅ Batch processing (size: 10 items, timeout: 30s)
- ✅ NER (Named Entity Recognition) for location extraction
- ✅ Sentiment analysis (negative = more threatening)
- ✅ Trend detection (increasing/decreasing threat)
- ✅ Keyword matching (584 security keywords)
- ✅ Deduplication via vector similarity + MD5 hashing

---

## 👤 USER MANAGEMENT

### Profile Endpoints
```
GET    /profile/me                 - Get current user profile
POST   /profile/update             - Update profile (name, preferences)
GET    /profile/settings           - Get notification preferences
POST   /profile/settings           - Update notification settings
```

### Plan Management
```
GET    /user/plan                  - Get current plan details + usage
POST   /user/plan/upgrade          - Upgrade to paid plan (stripe)
POST   /user/plan/cancel           - Cancel subscription
```

### Plans
- **FREE** - Basic threat assessment (5/day)
- **PRO** - Professional (unlimited chats, itineraries, $9.99/mo)
- **BUSINESS** - Enterprise (route analysis, team mgmt, custom)

### Features
- ✅ Profile customization
- ✅ Notification preferences (email, push, SMS)
- ✅ Geofence alerts (custom radius per region)
- ✅ Saved destinations (favorites)
- ✅ Integration webhooks (Slack, Teams, custom)

---

## 📊 REPORTING & EXPORTS

### Export Endpoints
```
GET    /export/history             - PDF export history
POST   /export/pdf                 - Generate PDF threat report
POST   /export/csv                 - Export threats as CSV
```

### Newsletter
```
GET    /newsletter/status          - Get newsletter subscription status
POST   /newsletter/subscribe       - Subscribe to weekly digest
POST   /newsletter/unsubscribe     - Unsubscribe from digest
```

### Features
- ✅ PDF export (threats + map + recommendations)
- ✅ CSV export (bulk data download)
- ✅ Weekly digest newsletter (compiled threats)
- ✅ Email delivery (UNMETERED, requires PAID plan)
- ✅ Export history tracking

---

## ⚙️ ADMIN OPERATIONS

### Database Management
```
GET    /admin/db/tables            - List all tables + row counts
POST   /admin/db/vacuum            - Run PostgreSQL VACUUM
POST   /admin/db/analyze           - Analyze table statistics
```

### Geocoding
```
POST   /admin/geocoding/migrate    - Run bulk geocoding operation
POST   /admin/opencage/migrate     - Migrate from OpenCage API
GET    /admin/opencage/quota       - Check OpenCage quota usage
```

### User Management
```
POST   /admin/user/plan            - Assign plan to user
POST   /admin/user/role            - Assign admin role
GET    /admin/users                - List all users (pagination)
```

### Retention & Cleanup
```
GET    /admin/retention/status     - Check data retention status
POST   /admin/retention/cleanup    - Run retention job (delete old data)
```

### Threat Data
```
POST   /admin/acled/run            - Force ACLED data refresh
GET    /admin/rss/diag             - RSS ingestion diagnostics
POST   /admin/rss/reprocess        - Reprocess failed feeds
```

### Infrastructure
```
GET    /admin/postgis/status       - Check PostGIS installation
POST   /admin/migration/apply      - Run pending database migrations
```

### Rate Limiting
- All admin endpoints restricted to ADMIN role
- No rate limiting (trusted endpoints)
- Requires authentication + admin flag

---

## 🚩 FEATURE FLAGS & PLAN GATING

### Plan-Based Feature Access
```python
@feature_required('route_analysis', required_plan='BUSINESS')
def analyze_route_risk():
    """Only BUSINESS plan users can call this"""
```

### Usage Metering
```python
@feature_limit('chats_per_day', required_plan='PRO', limit_message='You have used all chats today')
def chat():
    """Count usage toward daily limit"""
```

### Current Features
| Feature | FREE | PRO | BUSINESS |
|---------|------|-----|----------|
| Travel Risk Assess | 5/day | Unlimited | Unlimited |
| Chat Advisory | 10/day | 100/day | Unlimited |
| Itineraries | 5 total | Unlimited | Unlimited |
| Route Analysis | ❌ | ❌ | ✅ |
| PDF Export | ❌ | ✅ | ✅ |
| Email Notifications | ❌ | ✅ | ✅ |
| API Access | ❌ | ✅ | ✅ |
| Webhooks | ❌ | ❌ | ✅ |

### UNMETERED Features (All Plans)
- ✅ Authentication
- ✅ Email verification
- ✅ Profile access
- ✅ Newsletter (if subscribed)
- ✅ Health checks

---

## 📦 DATABASE MODELS

### Core Tables
```
users
├── id, email, password_hash
├── plan (FREE/PRO/BUSINESS)
├── created_at, updated_at
└── is_email_verified, deleted_at

alerts
├── id, source (GDELT/RSS/ACLED)
├── title, summary, description
├── latitude, longitude (PostGIS point)
├── city, country, region
├── threat_level (LOW/MODERATE/HIGH/SEVERE)
├── categories (array)
├── created_at, updated_at
└── metadata (JSONB)

travel_itineraries
├── id, user_id, itinerary_uuid
├── title, description
├── data (JSONB: destinations, routes, settings)
├── version (for optimistic locking)
├── is_deleted, deleted_at (soft delete)
└── created_at, updated_at

chat_history
├── id, user_id
├── messages (array: role + content)
├── created_at
└── metadata (model, tokens, etc.)

push_subscriptions
├── id, user_id
├── endpoint, auth, p256dh
└── created_at

webhooks
├── id, user_id
├── url, event_types (array)
├── is_active, created_at
└── last_triggered_at
```

### Indexes
- `alerts(latitude, longitude)` - Geospatial queries
- `alerts(created_at)` - Time range queries
- `users(email)` - Auth lookups
- `chat_history(user_id, created_at)` - History retrieval
- `travel_itineraries(user_id, is_deleted)` - User itinerary lists

---

## 🔗 EXTERNAL INTEGRATIONS

### LLM Services
- **OpenAI (GPT-4)** - $0.03/1K tokens (primary)
- **Grok (XAI)** - $5/month (secondary)
- **DeepSeek** - Free (fallback)
- **Moonshot** - Free tier (tertiary)

### Email & Notifications
- **Brevo (formerly Sendinblue)** - Transactional email service
- **SMTP Fallback** - Custom SMTP server
- **Telegram** - Bot notifications
- **Web Push** - Browser notifications (if user enables)

### Data Sources
- **GDELT Project** - Global event database
- **ACLED** - Conflict location data
- **OpenCage** - Reverse geocoding (backup)
- **Custom RSS Feeds** - User-subscribed sources

### Maps & Geolocation
- **Mapbox** - Map rendering (frontend)
- **PostGIS** - Geographic queries (backend)
- **Nominatim** - Reverse geocoding (fallback)

---

## 📈 PERFORMANCE & OPTIMIZATION

### Caching Strategy
- **Redis:** Travel risk assessments (TTL: 24h)
- **Memory:** Last 100 queries (per process)
- **Database:** Indexes on frequently queried fields
- **HTTP:** Gzip compression (>500 bytes)

### Rate Limits (Customizable)
```
/auth/login         - 5/min per IP
/chat              - 10/day per FREE user, 100/day per PRO
/travel-risk/assess - 5/day per FREE user, unlimited per paid
/api/*              - 100/min per user (general)
```

### Database Optimization
- Batch inserts (10 items per batch)
- Connection pooling (min: 1, max: 10)
- Statement timeouts (30s default)
- VACUUM + ANALYZE on schedule

---

## 🚀 DEPLOYMENT & OPERATIONS

### Environment Variables (Required)
```
DATABASE_URL              - PostgreSQL connection string
OPENAI_API_KEY           - OpenAI API key
JWT_SECRET               - Secret for JWT signing
BREVO_API_KEY            - Email service API key
GDELT_API_KEY            - GDELT data access
XAI_API_KEY              - Grok/XAI API key
DEEPSEEK_API_KEY         - DeepSeek API key
```

### Railway Cron Jobs
- `python workers/cron_location_quality.py` - 7am UTC daily
- `python workers/retention_worker.py` - 2am UTC daily
- `python workers/newsletter_digest.py` - 6am UTC daily
- RSS ingestion - Hourly (delegated to cron)

### Health Checks
```
GET /health         - Full system check (DB + cache + LLM)
GET /health/quick   - Basic health (no DB queries)
GET /ping           - Liveliness probe (instant)
```

---

## 📝 NOTES FOR TEAM

### Current Status
- ✅ Authentication fully functional
- ✅ Travel risk assessment operational
- ✅ Chat advisory with multi-provider LLM routing
- ✅ RSS feed processing with batch optimization
- ✅ Cron jobs (no infinite hangs - fixed Dec 6)
- ✅ Email notifications (async, non-blocking)
- ✅ Database optimization (PostGIS ready)

### Recent Fixes (Dec 6, 2025)
1. Fixed `/api/travel-risk/assess` 500 error (import path)
2. Fixed `cron_location_quality.py` infinite run (email params + timeout)
3. Expanded stats endpoint with destinations_tracked, upcoming_trips_next_30d
4. Added real threat analysis to route endpoints (not placeholders)

### Ready for Frontend Integration
- All CRUD operations for itineraries ✅
- Pagination support ✅
- Optimistic concurrency (ETag/If-Match) ✅
- Error codes and messages standardized ✅
- CORS enabled globally ✅

---

**Last Updated:** December 6, 2025  
**Maintained By:** Sentinel AI Team  
**Questions?** Check `/docs/` for detailed endpoint specs or run `curl http://localhost:5000/health`
