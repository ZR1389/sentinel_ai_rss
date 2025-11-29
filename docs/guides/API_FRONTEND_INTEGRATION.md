# PDF Export & Weekly Digest API - Frontend Integration Guide

## 🎯 Phase 1: PDF Export (✅ LIVE)

### POST `/api/export/pdf`
Generate branded PDF from threat alert data.

**Authentication**: Required (JWT Bearer token)

**Request**:
```typescript
POST /api/export/pdf
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "template": "threat_alert",          // or "weekly_digest"
  "data": {
    "title": "Security Alert: Protests in Karachi",
    "severity": "HIGH",                // CRITICAL, HIGH, MEDIUM, LOW
    "threat_score": 7.5,              // 0-10
    "city": "Karachi",
    "country": "Pakistan",
    "published_at": "2025-11-25 14:30 UTC",
    "source_name": "ACLED",
    "summary": "Large protests...",
    "description": "Full details...",  // optional
    "categories": ["Protests", "Security"],
    "recommendations": "Avoid area...",
    "latitude": 24.8607,
    "longitude": 67.0011,
    "link": "https://acleddata.com/..."
  },
  "filename": "karachi_alert_20251125",  // optional, auto-generated if omitted
  "options": {                            // optional
    "page_size": "A4",                    // A4, Letter, Legal
    "primary_color": "#2563eb"            // hex color for branding
  }
}
```

**Success Response (200)**:
```json
{
  "ok": true,
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "/downloads/550e8400-e29b-41d4-a716-446655440000.pdf",
  "filename": "karachi_alert_20251125.pdf",
  "expires_at": "2025-11-26T14:30:00Z",
  "usage": {
    "used": 1,
    "limit": 10,        // null = unlimited
    "remaining": 9
  }
}
```

**Rate Limit Response (429)**:
```json
{
  "error": "Monthly PDF export limit reached",
  "feature_locked": true,
  "usage": {
    "used": 10,
    "limit": 10,
    "remaining": 0
  },
  "upgrade_plans": ["BUSINESS", "ENTERPRISE"]
}
```

**Plan Limits**:
- FREE: 1 PDF/month
- PRO: 10 PDFs/month
- BUSINESS: Unlimited
- ENTERPRISE: Unlimited

---

### GET `/downloads/<file_id>.pdf`
Download generated PDF (24h expiry).

**Authentication**: Required (JWT Bearer token)

**Success Response**: PDF file stream
**Error Responses**:
- 404: File not found
- 403: Unauthorized (not your file)
- 410: File expired

---

## 🎯 Phase 2: Weekly Digest Scheduling (✅ NEW)

### POST `/api/reports/weekly/schedule`
Create recurring weekly digest email.

**Authentication**: Required

**Request**:
```typescript
POST /api/reports/weekly/schedule
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "timezone": "Asia/Karachi",         // IANA timezone
  "hour": 9,                          // 0-23 (local time)
  "day_of_week": 0,                   // 0=Monday, 6=Sunday
  "filters": {                         // optional
    "countries": ["Pakistan", "India"],
    "severity": ["HIGH", "CRITICAL"],
    "categories": ["Security", "Terrorism"]
  }
}
```

**Success Response (200)**:
```json
{
  "ok": true,
  "schedule_id": 42,
  "timezone": "Asia/Karachi",
  "hour": 9,
  "day_of_week": 0,
  "next_run": "2025-12-02T04:00:00Z",  // UTC time
  "active": true
}
```

**Rate Limit Response (429)**:
```json
{
  "error": "Maximum 1 weekly digest schedules reached",
  "feature_locked": true,
  "current_count": 1,
  "limit": 1,
  "upgrade_plans": ["BUSINESS", "ENTERPRISE"]
}
```

**Plan Limits**:
- FREE: 0 schedules (feature disabled)
- PRO: 1 schedule
- BUSINESS: 3 schedules
- ENTERPRISE: Unlimited

---

### GET `/api/reports/weekly/<schedule_id>/status`
Get schedule details and execution history.

**Authentication**: Required

**Success Response (200)**:
```json
{
  "id": 42,
  "email": "user@example.com",
  "timezone": "Asia/Karachi",
  "hour": 9,
  "day_of_week": 0,
  "filters": {
    "countries": ["Pakistan"],
    "severity": ["HIGH", "CRITICAL"]
  },
  "template": "weekly_digest",
  "active": true,
  "created_at": "2025-11-25T10:30:00",
  "last_run": "2025-11-25T04:00:00Z",
  "next_run": "2025-12-02T04:00:00Z",
  "failure_count": 0
}
```

---

### DELETE `/api/reports/weekly/<schedule_id>`
Cancel/deactivate a weekly digest schedule.

**Authentication**: Required

**Success Response (200)**:
```json
{
  "ok": true,
  "message": "Schedule deactivated"
}
```

---

### GET `/api/reports/weekly/schedules`
List all schedules for current user.

**Authentication**: Required

**Success Response (200)**:
```json
{
  "ok": true,
  "schedules": [
    {
      "id": 42,
      "timezone": "Asia/Karachi",
      "hour": 9,
      "day_of_week": 0,
      "filters": {"countries": ["Pakistan"]},
      "template": "weekly_digest",
      "active": true,
      "next_run": "2025-12-02T04:00:00Z",
      "failure_count": 0
    }
  ]
}
```

---

## 📋 Frontend Implementation Examples

### React Hook for PDF Export

```typescript
import { useState } from 'react';

interface PDFExportResponse {
  ok: boolean;
  id: string;
  url: string;
  filename: string;
  expires_at: string;
  usage: {
    used: number;
    limit: number | null;
    remaining: number | null;
  };
}

export function usePDFExport() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const exportToPDF = async (alertData: any): Promise<string | null> => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/export/pdf', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('jwt')}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          template: 'threat_alert',
          data: alertData
        })
      });

      if (response.status === 429) {
        const data = await response.json();
        setError(`Limit reached: ${data.usage.used}/${data.usage.limit}. Upgrade to ${data.upgrade_plans[0]}?`);
        return null;
      }

      if (!response.ok) {
        throw new Error('Export failed');
      }

      const data: PDFExportResponse = await response.json();
      
      // Trigger download
      window.location.href = data.url;
      
      return data.url;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
      return null;
    } finally {
      setLoading(false);
    }
  };

  return { exportToPDF, loading, error };
}
```

### React Component for Weekly Digest

```typescript
import { useState } from 'react';

interface DigestSchedule {
  timezone: string;
  hour: number;
  day_of_week: number;
  filters?: {
    countries?: string[];
    severity?: string[];
    categories?: string[];
  };
}

export function WeeklyDigestForm() {
  const [schedule, setSchedule] = useState<DigestSchedule>({
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    hour: 9,
    day_of_week: 0,
    filters: {}
  });

  const createSchedule = async () => {
    const response = await fetch('/api/reports/weekly/schedule', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('jwt')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(schedule)
    });

    if (response.status === 403) {
      const data = await response.json();
      alert(`${data.error} - Upgrade to ${data.required_plan}`);
      return;
    }

    if (response.status === 429) {
      const data = await response.json();
      alert(`Limit reached: ${data.current_count}/${data.limit} schedules`);
      return;
    }

    if (response.ok) {
      const data = await response.json();
      alert(`Digest scheduled! Next run: ${new Date(data.next_run).toLocaleString()}`);
    }
  };

  return (
    <form onSubmit={(e) => { e.preventDefault(); createSchedule(); }}>
      <select 
        value={schedule.day_of_week}
        onChange={(e) => setSchedule({...schedule, day_of_week: parseInt(e.target.value)})}
      >
        <option value={0}>Monday</option>
        <option value={1}>Tuesday</option>
        <option value={2}>Wednesday</option>
        <option value={3}>Thursday</option>
        <option value={4}>Friday</option>
        <option value={5}>Saturday</option>
        <option value={6}>Sunday</option>
      </select>

      <input
        type="number"
        min={0}
        max={23}
        value={schedule.hour}
        onChange={(e) => setSchedule({...schedule, hour: parseInt(e.target.value)})}
        placeholder="Hour (0-23)"
      />

      <button type="submit">Schedule Weekly Digest</button>
    </form>
  );
}
```

---

## 🚀 Deployment Status

### Phase 1 (PDF Export): ✅ DEPLOYED
- Migration applied: `migrate_pdf_exports_tracking.sql`
- Endpoints live: `/api/export/pdf`, `/downloads/<uuid>.pdf`
- System dependencies: WeasyPrint installed via nixpacks.toml

### Phase 2 (Weekly Digest): 🔄 PENDING DEPLOYMENT
1. **Run migration**:
   ```bash
   railway run psql $DATABASE_URL -f migrate_weekly_digest_schedules.sql
   ```

2. **Push to Railway**: Auto-deploys on git push

3. **Verify scheduler**: Check logs for "✓ Weekly digest scheduler started"

---

## 📊 Testing Checklist

### Phase 1 Tests
- ✅ PDF generation with real alert data
- ✅ Plan enforcement (FREE=1, PRO=10, BUSINESS/ENTERPRISE=unlimited)
- ✅ File expiry and download authentication
- ✅ Monthly usage reset

### Phase 2 Tests
- [ ] Create schedule with valid timezone
- [ ] Verify schedule limit enforcement by plan
- [ ] Confirm next_run calculation accuracy
- [ ] Test digest generation and email delivery
- [ ] Validate schedule deactivation after 5 failures

---

## 🔐 Security Notes

1. **Authentication**: All endpoints require valid JWT token
2. **Ownership validation**: Users can only access their own PDFs/schedules
3. **File expiry**: PDFs expire after 24h (alerts) or 7 days (digests)
4. **Rate limiting**: Plan-based limits enforced at API level
5. **Email security**: Brevo API key required for digest emails

---

## 📧 Support

- **Logs**: `railway logs` for production issues
- **Test suite**: `python test_pdf_export.py` for local validation
- **Database**: Use Railway dashboard SQL console for query debugging

---

## Version History

- **v2.0** (2025-11-25): Phase 2 - Weekly Digest Scheduling
- **v1.0** (2025-11-25): Phase 1 - PDF Export System
