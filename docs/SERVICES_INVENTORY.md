# SENTINEL AI RSS - SERVICES INVENTORY & CAPABILITY MATRIX

**Last Updated:** December 6, 2025  
**Version:** 2.0

---

## 📊 SERVICES MATRIX

### Legend
- ✅ = Implemented & Tested
- 🔄 = In Development
- 🚫 = Planned/Backlog
- ⚠️ = Deprecated/Legacy

---

## 🔐 AUTHENTICATION & SECURITY

| Service | Status | Endpoints | Coverage |
|---------|--------|-----------|----------|
| Email/Password Auth | ✅ | `/auth/register`, `/auth/login` | Full |
| JWT Token Management | ✅ | `/auth/refresh` | Full |
| Email Verification | ✅ | `/auth/verify/send`, `/auth/verify/confirm` | Full |
| Bearer Token Validation | ✅ | All protected routes | Full |
| Rate Limiting | ✅ | Per-endpoint configurable | Full |
| CORS Support | ✅ | Global preflight OPTIONS | Full |
| Password Hashing | ✅ | bcrypt (12 rounds) | Full |
| HTTPS Enforcement | ✅ | Railway SSL | Full |

---

## 🌍 TRAVEL RISK & GEOSPATIAL

| Service | Status | Details |
|---------|--------|---------|
| Travel Risk Assessment | ✅ | POST `/api/travel-risk/assess` - Multi-source threat fusion |
| Itinerary CRUD | ✅ | Full Create/Read/Update/Delete with optimistic locking |
| Route Analysis (Waypoints) | ✅ | POST `/api/travel-risk/route-analysis` - BUSINESS plan |
| Route Corridor Analysis | ✅ | POST `/api/travel-risk/route-corridor` - Point-to-point analysis |
| Itinerary Statistics | ✅ | GET `/api/travel-risk/itinerary/stats` - Expanded fields |
| Pagination Support | ✅ | Limit/offset on itinerary lists |
| ETag/If-Match Locking | ✅ | Optimistic concurrency control |
| Geospatial Queries | ✅ | PostGIS integration for proximity searches |
| Threat Deduplication | ✅ | Vector similarity + MD5 hashing |

**Data Sources:**
- GDELT (Global conflict events)
- RSS Feeds (Custom + curated)
- ACLED (Armed conflict data)
- SOCMINT (Social media signals)

---

## 💬 CHAT & ADVISORY

| Service | Status | Details |
|---------|--------|---------|
| Chat Advisory | ✅ | POST `/chat` - Multi-turn conversations |
| Chat History | ✅ | GET `/chat/history` - Per-user persistence |
| LLM Provider Routing | ✅ | Grok → OpenAI → DeepSeek fallback |
| Tactical Recommendations | ✅ | Context-aware security advice |
| Feedback Collection | ✅ | POST `/chat/feedback` - Quality tracking |
| Usage Metering | ✅ | Count toward plan limits |
| Temperature Control | ✅ | Configurable per request |

**Providers (Fallback Order):**
1. Grok (XAI) - Primary
2. OpenAI (GPT-4) - Secondary
3. Moonshot - Tertiary
4. DeepSeek - Free fallback

---

## 📥 DATA INGESTION & PROCESSING

| Service | Status | Details |
|---------|--------|---------|
| RSS Feed Ingestion | ✅ | Hourly via Railway cron |
| GDELT Data Import | ✅ | Daily conflict event sync |
| ACLED Integration | ✅ | Armed conflict location data |
| Batch Processing | ✅ | 10 items/batch, 30s timeout |
| NER (Entity Recognition) | ✅ | spaCy model for location extraction |
| Sentiment Analysis | ✅ | Threat scoring based on tone |
| Keyword Matching | ✅ | 584 security keywords |
| Deduplication | ✅ | Multi-source event merging |
| Threat Scoring | ✅ | Severity + risk calculation |
| Anomaly Detection | ✅ | Quality monitoring |

**Processing Pipeline:**
Ingestion → Normalization → Enrichment → Scoring → Deduplication → Storage → Notification

---

## 👤 USER MANAGEMENT

| Service | Status | Details |
|---------|--------|---------|
| User Profile | ✅ | GET/POST `/profile/me`, `/profile/update` |
| Notification Settings | ✅ | Per-channel preferences (email, push, SMS) |
| Geofence Alerts | ✅ | Custom radius + region configuration |
| Saved Destinations | ✅ | Favorite locations |
| Plan Management | ✅ | Upgrade/downgrade/cancel |
| Usage Tracking | ✅ | Per-feature metering |
| Integration Webhooks | ✅ | Custom event endpoints |

**Plans:**
- FREE - Basic (limited)
- PRO - Professional ($9.99/mo)
- BUSINESS - Enterprise (custom)

---

## 📊 REPORTING & EXPORTS

| Service | Status | Details |
|---------|--------|---------|
| PDF Export | ✅ | POST `/export/pdf` - Threats + maps + recommendations |
| CSV Export | ✅ | POST `/export/csv` - Bulk data download |
| Export History | ✅ | GET `/export/history` - Per-user tracking |
| Weekly Newsletter | ✅ | Compiled threat digest |
| Email Delivery | ✅ | Brevo (transactional) + SMTP fallback |
| Push Notifications | ✅ | Web Push API (browser notifications) |
| Telegram Notifications | ✅ | Bot integration |
| Webhook Notifications | ✅ | Custom HTTP endpoints |

**Metering:**
- Email: UNMETERED (requires PAID plan)
- PDF: UNMETERED (requires PAID plan)
- Push: UNMETERED
- Webhooks: UNMETERED (BUSINESS plan)

---

## ⚙️ ADMIN OPERATIONS

| Service | Status | Details |
|---------|--------|---------|
| Database Management | ✅ | VACUUM, ANALYZE, migration running |
| Table Diagnostics | ✅ | Row counts, index status |
| Geocoding Operations | ✅ | Bulk validation, OpenCage migration |
| User Plan Assignment | ✅ | Admin override of user plans |
| User Role Management | ✅ | Admin flag assignment |
| Retention Policies | ✅ | Auto-cleanup of old data |
| ACLED Data Refresh | ✅ | Force reimport |
| RSS Diagnostics | ✅ | Feed status, error tracking |
| PostGIS Status | ✅ | Geographic DB extension check |

**Access Control:**
- Restricted to ADMIN role only
- No rate limiting
- Requires authentication

---

## 🔄 BACKGROUND JOBS & SCHEDULING

| Job | Schedule | Status | Purpose |
|-----|----------|--------|---------|
| RSS Ingestion | Hourly | ✅ | Fetch + process RSS feeds |
| GDELT Sync | Daily | ✅ | Import global conflict events |
| Location Quality Check | 7am UTC | ✅ | Anomaly detection + reporting |
| Newsletter Digest | 6am UTC | ✅ | Compile + send weekly report |
| Data Retention | 2am UTC | ✅ | Clean up old alerts |
| Weekly Digest Scheduler | Daily | ✅ | Schedule digest generation |

**Execution:**
- Railway cron jobs (not in web process)
- No infinite loops (fixed Dec 6)
- Timeout protection on all jobs
- Fallback notifications (email + webhook)

---

## 🗄️ DATA PERSISTENCE

| Component | Type | Status | Details |
|-----------|------|--------|---------|
| PostgreSQL DB | Primary | ✅ | Main data store |
| PostGIS | Extension | ✅ | Geographic queries |
| Redis Cache | Cache | ✅ | When available |
| Memory Cache | Fallback | ✅ | Last 100 queries |
| Connection Pooling | Optimization | ✅ | 1-10 connections |

**Tables:**
- `users` - User accounts + plans
- `alerts` - Threats from all sources
- `travel_itineraries` - User-saved routes
- `chat_history` - Conversation logs
- `push_subscriptions` - Browser push endpoints
- `webhooks` - Custom integrations
- `features` - Feature flags

---

## 🔗 EXTERNAL INTEGRATIONS

| Service | Status | Purpose | Cost |
|---------|--------|---------|------|
| OpenAI (GPT-4) | ✅ | LLM advisory | ~$0.03/1K tokens |
| Grok (XAI) | ✅ | Fast LLM (primary) | $5/month |
| DeepSeek | ✅ | Free LLM fallback | Free |
| Moonshot | ✅ | Alternative LLM | Free tier |
| Brevo Email | ✅ | Transactional emails | 300/day free |
| SMTP Fallback | ✅ | Email backup | Custom |
| Telegram | ✅ | Bot notifications | Free (with token) |
| GDELT | ✅ | Global events | Free |
| ACLED | ✅ | Conflict data | Free |
| Nominatim | ✅ | Reverse geocoding | Free (rate limited) |
| OpenCage | ✅ | Geocoding backup | $0.50/1K requests |
| Mapbox | ✅ | Map rendering (FE) | $0-200/mo |

---

## 📈 PERFORMANCE CHARACTERISTICS

### API Response Times
| Endpoint | Avg Time | Max Time | Cached |
|----------|----------|----------|--------|
| `/auth/login` | 200ms | 500ms | No |
| `/api/travel-risk/assess` (cached) | 50ms | 100ms | Yes (24h) |
| `/api/travel-risk/assess` (fresh) | 2-5s | 10s | No |
| `/chat` | 3-8s | 20s | No |
| `/api/travel-risk/itinerary` (list) | 100ms | 500ms | No |
| `/health/quick` | 10ms | 50ms | No |

### Throughput
- **Concurrent users:** ~100 (without load balancing)
- **Requests/second:** ~50 (average load)
- **Database queries/second:** ~200 (peak)
- **Cache hit rate:** ~60% (travel risk assessments)

### Storage
- **Database size:** ~500MB (196 alerts baseline)
- **Growth rate:** ~50MB/month (typical usage)
- **Retention:** 6 months (configurable)

---

## 🚀 DEPLOYMENT STATUS

### Current Environment
- **Platform:** Railway
- **Region:** US-based
- **SSL:** Auto-managed (Railway)
- **Database:** Managed PostgreSQL
- **Cache:** Optional Redis

### Recent Fixes (Dec 6, 2025)
1. ✅ Fixed `/api/travel-risk/assess` 500 error (import path)
2. ✅ Fixed `cron_location_quality.py` infinite run (email params + timeout)
3. ✅ Expanded stats endpoint (destinations_tracked, upcoming_trips_next_30d)
4. ✅ Implemented real threat analysis in route endpoints
5. ✅ Added dedicated route-corridor endpoint

### Production Readiness
- ✅ Authentication robust
- ✅ Error handling comprehensive
- ✅ Rate limiting active
- ✅ Database optimized
- ✅ Caching implemented
- ✅ Monitoring in place
- ✅ Cron jobs protected (timeouts)

---

## 📋 RECOMMENDATIONS FOR FRONTEND TEAM

### Must Implement
1. ✅ JWT token refresh before expiry (24h)
2. ✅ ETag-based optimistic locking on PATCH requests
3. ✅ Plan gating checks (403 responses)
4. ✅ Rate limit handling (429 backoff)
5. ✅ Error message display to users

### Nice to Have
1. Pagination on long lists (has_next, next_offset)
2. Caching of travel risk assessments
3. Offline support for itinerary drafts
4. Webhook integration for real-time alerts
5. Analytics tracking (events per endpoint)

### Do NOT Implement (Backend Already Handles)
1. ❌ LLM provider selection (backend routes automatically)
2. ❌ Data deduplication (backend handles it)
3. ❌ Location geocoding (use backend endpoints)
4. ❌ Email sending (backend async)
5. ❌ Threat scoring (backend handles it)

---

## 🔄 ADD/REMOVE PLANNING

### Consider Adding
- [ ] Threat timeline visualization (history of threat levels)
- [ ] Batch itinerary import (CSV upload)
- [ ] Custom threat keyword management
- [ ] API key generation for programmatic access
- [ ] Team collaboration features (BUSINESS plan)
- [ ] Dark web monitoring integration

### Consider Removing
- [ ] Legacy ACLED polling (if not used)
- [ ] Deprecated geocoding method fallbacks
- [ ] Unused notification channels (SMS if no users)
- [ ] Old chat model support (after full migration to Grok)

### Monitor for Removal
- GDELT polling (if ELT elsewhere)
- Specific LLM provider (if consistently fails)
- Custom RSS feed (if never updated)
- Deprecated plan types

---

**Questions?** See `/docs/BACKEND_API_QUICK_REFERENCE.md` for API details or `/docs/` for more documentation.
