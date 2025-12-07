# Intelligence Reports System - Frontend Integration Guide

## Overview

The Intelligence Reports system allows users to request custom threat assessments, analysis, and reports. The backend generates professional PDFs with a multi-page structure. This guide covers what the frontend needs to implement and how users interact with the system.

---

## User Journey

### 1. **Request Creation** (User initiates tasking)
**Endpoint:** `POST /api/reports/request`
**Auth:** JWT (login_required)

User fills out a form:
- **Report Type** (required): threat_assessment | threat | travel | due_diligence | exec | custom
- **Target** (required): Country, person, organization, event, or location
- **Scope** (required): Geographic, temporal, or operational scope
- **Urgency** (optional): standard | priority | critical
- **Title** (optional): Short label for the request
- **Notes** (optional): User instructions and context
- **Context Links** (optional):
  - Chat ID (link to existing chat thread)
  - Itinerary ID (link to travel itinerary for travel risk analysis)
  - Alert IDs (link to specific alerts)

**Request Body Example:**
```json
{
  "report_type": "threat_assessment",
  "target": "Port City, Coastal Region",
  "scope": "30-day outlook, 30km radius, logistics sector",
  "urgency": "priority",
  "title": "Port City Cargo Security Assessment",
  "notes": "Focus on Route 7 corridor and cargo theft trends",
  "context": {
    "chat_id": "550e8400-e29b-41d4-a716-446655440000",
    "itinerary_id": "550e8400-e29b-41d4-a716-446655440001",
    "alert_ids": ["alert-123", "alert-456"]
  }
}
```

**Response:**
```json
{
  "ok": true,
  "request_id": "ZR-2025-000154",
  "status": "requested"
}
```

**Frontend Actions:**
- Show confirmation: "Report request submitted"
- Display request_id for user reference
- Optionally poll `GET /api/reports/{request_id}` to check status updates

---

### 2. **User Views Report List** (Dashboard)
**Endpoint:** `GET /api/reports/mine`
**Auth:** JWT (login_required)

Returns simplified preview list (no full report bodies).

**Response Example:**
```json
{
  "ok": true,
  "requests": [
    {
      "id": "ZR-2025-000154",
      "report_type": "threat_assessment",
      "title": "Port City Cargo Security",
      "target": "Port City",
      "urgency": "priority",
      "status": "draft",
      "reports_count": 1,
      "created_at": "2025-12-07T08:00:00Z",
      "updated_at": "2025-12-07T09:30:00Z"
    }
  ]
}
```

**Frontend Actions:**
- Display list in dashboard with status badges
- Link each request to detail view
- Show urgency as badge color (standard=gray, priority=yellow, critical=red)
- Show reports_count to indicate ready reports

---

### 3. **User Views Report Detail & Downloads PDF**
**Endpoints:**
- `GET /api/reports/{request_id}` - Full request + reports
- `GET /api/reports/{report_id}/download` - Download PDF (streamed)

**Auth:** JWT (must be report owner)

**GET /api/reports/{request_id} Response:**
```json
{
  "ok": true,
  "request": {
    "id": "ZR-2025-000154",
    "report_type": "threat_assessment",
    "title": "Port City Cargo Security",
    "target": "Port City",
    "scope": "30-day outlook, 30km radius",
    "urgency": "priority",
    "status": "delivered",
    "notes": "Focus on Route 7 corridor",
    "created_at": "2025-12-07T08:00:00Z",
    "updated_at": "2025-12-07T10:00:00Z"
  },
  "reports": [
    {
      "id": "report-uuid-123",
      "title": "Port City Threat Outlook",
      "confidence_level": "Medium",
      "generated_by": "ai",
      "pdf_url": "/api/reports/report-uuid-123/download",
      "delivered_at": "2025-12-07T10:00:00Z",
      "created_at": "2025-12-07T09:30:00Z"
    }
  ]
}
```

**Frontend Actions:**
- Display request metadata
- List associated reports
- Button: "Download PDF" → GET `/api/reports/{report_id}/download`
- Show pdf_url as actionable link
- Display confidence_level and generated_by (ai | human | hybrid)

---

## Admin/Analyst Workflow

### 4. **Analyst Reviews Request Queue**
**Endpoint:** `GET /admin/reports`
**Auth:** X-API-Key header (ADMIN_API_KEY)
**Optional Filters:**
- `status`: requested | triaged | in_progress | draft | delivered | cancelled
- `urgency`: standard | priority | critical
- `report_type`: threat_assessment | travel | due_diligence | exec | custom
- `sort`: urgency | date
- `limit`: number of results

**Response Example:**
```json
{
  "ok": true,
  "requests": [
    {
      "id": "ZR-2025-000154",
      "user_id": "user-123",
      "user_email": "client@example.com",
      "report_type": "threat_assessment",
      "title": "Port City Cargo Security",
      "target": "Port City",
      "urgency": "priority",
      "status": "triaged",
      "analyst_notes": "Assigned to Team A for analysis",
      "reports_count": 0,
      "created_at": "2025-12-07T08:00:00Z",
      "updated_at": "2025-12-07T08:30:00Z"
    }
  ]
}
```

**Frontend (Analyst Dashboard):**
- Show kanban board: requested → triaged → in_progress → draft → delivered
- Sort by urgency (critical first)
- Click request to open detail + workflow actions

---

### 5. **Analyst Initiates Draft**
**Endpoint:** `POST /admin/reports/{request_id}/draft`
**Auth:** X-API-Key header (ADMIN_API_KEY)

System collects:
- Travel risk data (if itinerary linked) via ThreatFusion
- Alert data (if alert_ids linked)
- User notes and analyst notes
- Calls LLM pipeline with full context

**Request Body (optional):**
```json
{
  "analyst_email": "analyst@sentinel-ai.com"
}
```

**Response:**
```json
{
  "ok": true,
  "message": "Draft generated",
  "report": {
    "id": "report-uuid-123",
    "body_length": 2500,
    "data_sources": {
      "travel_risk": {...},
      "alerts_count": 3
    }
  }
}
```

**Frontend (Analyst Dashboard):**
- Button: "Generate AI Draft" → POST endpoint
- Show spinner while generating
- Once done, auto-refresh request status to "draft"
- Show report preview link

---

### 6. **Analyst Finalizes & Generates PDF**
**Endpoint:** `POST /admin/reports/{request_id}/finalize`
**Auth:** X-API-Key header (ADMIN_API_KEY)

Converts report_body (markdown) → PDF using intelligent template.
Stores PDF in `downloads/intelligence_reports/`.

**Request Body:**
```json
{
  "report_id": "report-uuid-123",
  "analyst_email": "analyst@sentinel-ai.com"
}
```

**Response:**
```json
{
  "ok": true,
  "message": "Report finalized with PDF",
  "pdf_url": "/api/reports/report-uuid-123/download",
  "file_size": 245632,
  "pdf_path": "/home/zika/sentinel_ai_rss/downloads/intelligence_reports/report-uuid-123_1765126745.pdf",
  "delivered_at": "2025-12-07T10:00:00Z"
}
```

**Frontend (Analyst Dashboard):**
- Button: "Finalize & Generate PDF" → POST endpoint
- Show spinner while rendering PDF
- Once done, mark request status to "delivered"
- Display pdf_url and file_size
- Enable "Send to User" button

---

### 7. **Analyst Updates Status & Notes**
**Endpoint:** `POST /admin/reports/{request_id}/status`
**Auth:** X-API-Key header (ADMIN_API_KEY)

**Request Body:**
```json
{
  "status": "in_progress",
  "analyst_notes": "Analysis underway; will have draft by EOD"
}
```

**Frontend (Analyst Dashboard):**
- Dropdown to update status (with validation)
- Text field for analyst_notes
- Auto-save on change

---

## PDF Structure & Logo

### Multi-Page PDF Layout

Generated PDFs follow this structure:

1. **Cover Page**
   - Zika Risk Logo (placeholder box currently)
   - "INTELLIGENCE ASSESSMENT REPORT"
   - Report ID, Classification, Client Name, Analyst, Date

2. **Page 1: Executive Summary**
   - Assessment Purpose
   - Key Findings (bullets)
   - Overall Risk Level (LOW | MODERATE | HIGH | SEVERE)
   - Confidence Level
   - Immediate Recommendations

3. **Page 2: Scope & Methodology**
   - Data Sources (RSS, ACLED, GDELT, OSINT, SOCMINT)
   - Time Ranges Analyzed
   - Geographic Scope
   - Known Limitations

4. **Page 3: Threat Landscape**
   - Recent Incidents (table: Date, Type, Location, Severity)
   - Trend (Increasing | Stable | Decreasing)
   - Threat Categories (Political, Crime, Terrorism, Military)

5. **Page 4+: Detailed Analysis** (repeatable blocks)
   - Area / Target Analysis
   - Threat Actor Profile (if relevant)
   - Vulnerability Analysis
   - Full Narrative Report Body

6. **Optional: Travel Risk** (if itinerary linked)
   - Airport Risk Profile
   - Transport Risks
   - Hotel Zone Analysis
   - Safe Routes vs High-Risk Zones

7. **Optional: Map Snapshot**
   - Embedded static PNG or Risk Grid Table

8. **Final Page: Tactical & Strategic Recommendations**
   - Operational Security
   - Route Hardening
   - Avoidance Behaviors

9. **Appendix**
   - Sources (ACLED, local OSINT, etc.)
   - Processing Timestamps (ingest, analysis)
   - Engine Version

---

## Logo Implementation

### Current Status
**The template currently uses a placeholder box:**
```html
<div class="logo">Zika Risk</div>
```

### To Use Your Logo
You need to provide:
1. **Logo URL or Base64-encoded image**
2. **Dimensions** (suggested: 120px × 120px)

### Options

#### Option A: Use Frontend Logo URL (Recommended)
Modify `services/pdf/intelligence_report.py` to accept `logo_url`:

```python
def generate_intelligence_report_pdf(
    ...,
    logo_url: Optional[str] = None,
    ...
):
    context = {
        ...,
        "logo_url": logo_url or "https://your-frontend.com/assets/logo.png",
    }
```

Update template `services/pdf/templates/intelligence_report.html`:
```html
{% if logo_url %}
  <img src="{{ logo_url }}" alt="Logo" style="width: 120px; height: 120px;" />
{% else %}
  <div class="logo">Zika Risk</div>
{% endif %}
```

#### Option B: Embed Base64 from Frontend
Frontend sends base64-encoded logo in the request:
```json
POST /admin/reports/{request_id}/finalize
{
  "report_id": "...",
  "logo_base64": "data:image/png;base64,iVBORw0KGgo..."
}
```

Backend stores it directly in PDF context.

#### Option C: Store Static Logo in Backend
Place logo file at `services/pdf/templates/logo.png` and reference it:
```html
<img src="{{ logo_path }}" alt="Logo" style="width: 120px; height: 120px;" />
```

**Recommended:** Use **Option A** (frontend URL) since your logo lives in the frontend repo.

---

## Frontend Implementation Checklist

### Request Creation Form
- [ ] Text input: Report Type (dropdown)
- [ ] Text input: Target (required)
- [ ] Text area: Scope (required)
- [ ] Radio/Dropdown: Urgency (standard | priority | critical)
- [ ] Text input: Title (optional)
- [ ] Text area: Notes (optional)
- [ ] Optional: Link to existing chat, itinerary, alerts
- [ ] Submit button → POST `/api/reports/request`
- [ ] Show success with request_id

### User Dashboard
- [ ] List view: GET `/api/reports/mine`
- [ ] Display status badges (requested, triaged, in_progress, draft, delivered)
- [ ] Click to open detail view
- [ ] Show reports_count per request
- [ ] Link to download PDF (if status=delivered)

### Report Detail Page
- [ ] GET `/api/reports/{request_id}`
- [ ] Display request metadata
- [ ] List reports with timestamps
- [ ] "Download PDF" button → GET `/api/reports/{report_id}/download`
- [ ] Show confidence_level, generated_by, pdf_url

### Admin/Analyst Dashboard
- [ ] List view: GET `/admin/reports` with filters
- [ ] Kanban board view (status columns)
- [ ] Request cards show: type, target, urgency, status, reports_count
- [ ] Click request to open detail
- [ ] Actions: "Generate Draft", "Finalize PDF", "Update Status", "Send to User"
- [ ] Status update form with dropdown + notes text area

### API Integration
- [ ] JWT token in `Authorization: Bearer` header
- [ ] X-API-Key header for admin endpoints
- [ ] Handle 401/403 errors gracefully
- [ ] Show spinners during async operations (draft, finalize)
- [ ] Stream PDF downloads instead of API response bodies

---

## Testing Endpoints

### Request Creation
```bash
curl -X POST http://localhost:5000/api/reports/request \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "report_type": "threat_assessment",
    "target": "Port City",
    "scope": "30-day outlook, 30km radius",
    "urgency": "priority"
  }'
```

### User Reports List
```bash
curl http://localhost:5000/api/reports/mine \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Admin Reports List
```bash
curl "http://localhost:5000/admin/reports?status=requested&urgency=critical" \
  -H "X-API-Key: YOUR_ADMIN_API_KEY"
```

### Generate Draft
```bash
curl -X POST http://localhost:5000/admin/reports/ZR-2025-000154/draft \
  -H "X-API-Key: YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"analyst_email": "analyst@example.com"}'
```

### Finalize PDF
```bash
curl -X POST http://localhost:5000/admin/reports/ZR-2025-000154/finalize \
  -H "X-API-Key: YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"report_id": "report-uuid-123"}'
```

### Download PDF
```bash
curl -O http://localhost:5000/api/reports/report-uuid-123/download \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

---

## Summary

**User Flow:**
1. User creates report request (form)
2. User views dashboard (request list)
3. Analyst reviews queue (admin panel)
4. Analyst generates AI draft
5. Analyst finalizes & generates PDF
6. User downloads PDF from dashboard

**Frontend Needs:**
- Request creation form
- User dashboard with list/detail views
- Analyst admin panel with workflow actions
- PDF download integration
- Logo integration (pass frontend logo URL to backend)

**Database:** report_requests + reports tables (already created in backend)

**PDF:** Multi-page intelligent template with cover, exec summary, scope, threats, analysis, travel risk (optional), map (optional), recommendations, appendix
