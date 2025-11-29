# PDF Export System - Phase 1 Complete ✅

## Overview
Fully functional PDF export system with plan-gated monthly limits. Free users get 1 export/month, Pro users get 10/month, Business and Enterprise users get unlimited exports.

## Features Implemented

### 1. PDF Generation Endpoint
**POST `/api/export/pdf`**

Generate branded PDF reports from templates with automatic plan enforcement.

#### Request Body
```json
{
  "template": "threat_alert",
  "data": {
    "title": "Security Alert: Protests in Karachi",
    "severity": "HIGH",
    "threat_score": 7.5,
    "city": "Karachi",
    "country": "Pakistan",
    "published_at": "2025-11-25 14:30 UTC",
    "source_name": "ACLED",
    "summary": "Large-scale protests reported in downtown area...",
    "description": "Full incident description...",
    "categories": ["Protests", "Security"],
    "recommendations": "Avoid downtown area. Monitor local news.",
    "latitude": 24.8607,
    "longitude": 67.0011,
    "link": "https://acleddata.com/..."
  },
  "filename": "karachi_alert_20251125",
  "options": {
    "page_size": "A4",
    "margins": {"top": "2cm", "right": "2cm", "bottom": "2cm", "left": "2cm"},
    "primary_color": "#2563eb",
    "logo_url": null
  }
}
```

#### Response (Success)
```json
{
  "ok": true,
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "/downloads/550e8400-e29b-41d4-a716-446655440000.pdf",
  "filename": "karachi_alert_20251125.pdf",
  "expires_at": "2025-11-26T14:30:00Z",
  "usage": {
    "used": 1,
    "limit": 10,
    "remaining": 9
  }
}
```

#### Response (Limit Exceeded)
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

### 2. Authenticated Download Endpoint
**GET `/downloads/<file_id>.pdf`**

Download generated PDFs with security validation:
- Requires valid JWT authentication
- Validates file ownership (user_id match)
- Checks expiry (24h default)
- Streams PDF with proper headers

#### Security Features
- UUID validation
- Ownership verification
- Expiry enforcement (410 Gone for expired files)
- Unauthorized access logging and metrics

### 3. Plan Limits
Monthly PDF export quotas enforced at API level:

| Plan       | PDFs/Month | Cost    |
|------------|-----------|---------|
| FREE       | 1         | $0      |
| PRO        | 10        | $79/mo  |
| BUSINESS   | Unlimited | $149/mo |
| ENTERPRISE | Unlimited | $299/mo |

### 4. Templates

#### Available Templates
1. **threat_alert.html** - Single threat/security alert PDF
2. **weekly_digest.html** - Coming in Phase 2
3. **travel_brief.html** - Coming in Phase 2

#### Template Inheritance
All templates extend `base.html` which provides:
- Branded header with logo support
- CSS Paged Media for page numbers
- Responsive styling
- Professional PDF formatting
- Footer with disclaimers

#### Customization Options
- `page_size`: A4, Letter, Legal
- `margins`: Top, right, bottom, left (in cm or mm)
- `primary_color`: Hex color for branding (#2563eb default)
- `logo_url`: Custom logo URL (optional)

## Database Schema

### New Table: `pdf_exports`
```sql
CREATE TABLE pdf_exports (
    id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    template VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    downloaded_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX idx_pdf_exports_user_id ON pdf_exports(user_id);
CREATE INDEX idx_pdf_exports_expires_at ON pdf_exports(expires_at);
CREATE INDEX idx_pdf_exports_created_at ON pdf_exports(created_at DESC);
```

### Updated Column: `user_usage.pdf_exports_used`
```sql
ALTER TABLE user_usage 
ADD COLUMN pdf_exports_used INTEGER DEFAULT 0 NOT NULL;
```

Monthly reset logic in `plan_utils._maybe_monthly_reset()` now resets both `chat_messages_used` and `pdf_exports_used` on first-of-month.

## Testing

### Test Suite: `test_pdf_export.py`
Run: `python test_pdf_export.py`

**All 4 tests passing:**
1. ✅ Template Rendering - Jinja2 template loading and rendering
2. ✅ PDF Generation - WeasyPrint HTML→PDF conversion
3. ✅ Real Alert Data - Database query and PDF generation with production data
4. ✅ Plan Limits - Correct monthly limits configured for all plans

### Sample PDFs Generated
- `/tmp/test_alert.html` - Rendered HTML for inspection
- `/tmp/test_alert.pdf` - Test PDF from sample data
- `/tmp/real_alert.pdf` - PDF from real database alert

## Usage Examples

### Frontend Integration (React/Next.js)

```typescript
// Generate PDF export
async function exportThreatAlert(alertId: string) {
  const alert = await fetchAlert(alertId);
  
  const response = await fetch('/api/export/pdf', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${jwt}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      template: 'threat_alert',
      data: alert,
      filename: `alert_${alertId}`,
      options: {
        primary_color: '#2563eb'
      }
    })
  });
  
  const result = await response.json();
  
  if (result.ok) {
    // Trigger download
    window.location.href = result.url;
    
    // Show usage info
    console.log(`PDFs used: ${result.usage.used}/${result.usage.limit}`);
  } else if (response.status === 429) {
    // Show upgrade prompt
    showUpgradeModal(result.upgrade_plans);
  }
}
```

### Backend/Admin Usage

```python
from main import app
import requests

# Generate PDF for user
with app.test_client() as client:
    response = client.post('/api/export/pdf',
        json={
            'template': 'threat_alert',
            'data': {
                'title': 'Emergency Alert',
                'severity': 'CRITICAL',
                'summary': '...',
                # ... more fields
            }
        },
        headers={'Authorization': f'Bearer {user_jwt}'}
    )
    
    if response.status_code == 200:
        data = response.json()
        file_id = data['id']
        download_url = data['url']
        print(f"PDF ready: {download_url}")
```

## Metrics and Monitoring

### Tracked Metrics
- `pdf_exports.generated` - Count of successful PDF generations (tagged by plan, template)
- `pdf_exports.error` - Count of generation errors (tagged by error_type)
- `pdf_exports.downloaded` - Count of successful downloads
- `pdf_exports.unauthorized_access` - Count of unauthorized access attempts

### Logs
```
INFO: PDF export generated: user=test@example.com, plan=PRO, template=threat_alert, id=550e8400...
WARNING: Unauthorized PDF access attempt: user=hacker@example.com, file=550e8400...
ERROR: PDF file missing from disk: downloads/550e8400-e29b-41d4-a716-446655440000.pdf
```

## File Management

### Storage Location
- Local: `/home/zika/sentinel_ai_rss/downloads/`
- Railway: Mounted persistent volume at `/downloads`

### Expiry and Cleanup
- **Default expiry**: 24 hours from generation
- **Cleanup strategy**: Manual or cron job to delete expired files
  ```bash
  # Cleanup script (run daily)
  psql $DATABASE_URL -c "DELETE FROM pdf_exports WHERE expires_at < NOW();"
  find /path/to/downloads -name "*.pdf" -mtime +1 -delete
  ```

### Railway Volume Configuration
Add to `railway.toml`:
```toml
[volumes]
downloads = "/downloads"
```

## Next Steps (Phase 2 - Not Built Yet)

### Weekly Digest Scheduling
- `POST /api/reports/weekly/schedule` - Schedule recurring digest emails
- `GET /api/reports/weekly/:scheduleId/status` - Check schedule status
- `DELETE /api/reports/weekly/:scheduleId` - Cancel schedule
- APScheduler background job: runs daily at 6am, generates PDFs, emails via Brevo
- Template: `weekly_digest.html` with multi-alert summary

### Future Enhancements (Phase 3)
- Webhook subscriptions for real-time PDF delivery
- CSV export for Business+ plans
- JSON export for API integration
- Custom branding (logo, colors, footer text) per organization

## Deployment Notes

### Railway Requirements
1. **System Dependencies**: WeasyPrint requires system libs (libpango, libgdk-pixbuf)
   - Add to `nixpacks.toml`:
     ```toml
     [phases.setup]
     aptPkgs = ["libpango-1.0-0", "libpangoft2-1.0-0", "libgdk-pixbuf2.0-0", "libffi-dev", "libjpeg-dev"]
     ```

2. **Environment Variables**: None required (uses existing DATABASE_URL, JWT_SECRET)

3. **Persistent Volume**: Mount `/downloads` for PDF storage

4. **Database Migration**: Run `migrate_pdf_exports_tracking.sql` on first deploy

### Local Development
```bash
# Install dependencies
pip install WeasyPrint

# Run migration
psql $DATABASE_URL -f migrate_pdf_exports_tracking.sql

# Run tests
python test_pdf_export.py

# Start server
python main.py
```

## Success Criteria ✅

- [x] WeasyPrint installed and working
- [x] PDF templates created (base.html + threat_alert.html)
- [x] /api/export/pdf endpoint implemented
- [x] /downloads/<uuid>.pdf download route implemented
- [x] Plan gating enforced (FREE=1, PRO=10, BUSINESS/ENTERPRISE=unlimited)
- [x] Monthly usage tracking and reset
- [x] Database migrations applied
- [x] All 4 tests passing
- [x] Generated PDFs validated with real alert data
- [x] Security features: JWT auth, ownership validation, expiry checks
- [x] Metrics and logging in place
- [x] Committed and pushed to GitHub

## Support

For issues or questions:
1. Check logs: `railway logs` or local console
2. Verify plan limits: `GET /api/profile/me` to see current usage
3. Test PDF generation: Run `python test_pdf_export.py`
4. Review templates: Check `templates/pdf/*.html` for syntax errors

## Version
**Phase 1 Complete**: 2025-11-25
**Commit**: 2120acf - "feat: Phase 1 - PDF Export System with plan gating"
