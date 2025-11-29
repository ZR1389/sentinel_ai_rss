# Weekly Digest Frontend Integration Guide

## Newsletter Endpoint

**Subscribe to Newsletter**
```
POST /newsletter/subscribe
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "ok": true
}
```

**Notes:**
- Requires verified email
- Uses Brevo Contacts API (not email sending)
- Idempotent (already subscribed = success)

---

## Weekly Digest Endpoints

### 1. Create Schedule

**Request:**
```
POST /api/reports/weekly/schedule
Authorization: Bearer <jwt_token>
Content-Type: application/json
```

**Body:**
```json
{
  "timezone": "America/New_York",
  "hour": 9,
  "day_of_week": 1,
  "filters": {
    "countries": ["United States", "Canada"],
    "categories": ["terrorism", "conflict"],
    "severity": ["HIGH", "CRITICAL"]
  }
}
```

**Response (201):**
```json
{
  "schedule_id": 42,
  "next_run": "2025-12-01T14:00:00Z",
  "message": "Weekly digest scheduled"
}
```

**Errors:**
- `429`: Plan limit exceeded (FREE=0, PRO=1, BUSINESS=3, ENTERPRISE=∞)
- `400`: Invalid timezone/hour/day_of_week
- `401`: Not authenticated

**TypeScript Example:**
```typescript
interface CreateScheduleRequest {
  timezone: string; // IANA timezone (e.g., "Asia/Karachi")
  hour: number; // 0-23
  day_of_week: number; // 0=Monday, 6=Sunday
  filters?: {
    countries?: string[];
    categories?: string[];
    severity?: string[];
  };
}

async function createSchedule(data: CreateScheduleRequest): Promise<{schedule_id: number, next_run: string}> {
  const response = await fetch('/api/reports/weekly/schedule', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });
  
  if (response.status === 429) {
    throw new Error('Schedule limit reached. Upgrade your plan.');
  }
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to create schedule');
  }
  
  return response.json();
}
```

---

### 2. List User Schedules

**Request:**
```
GET /api/reports/weekly/schedules
Authorization: Bearer <jwt_token>
```

**Response (200):**
```json
{
  "schedules": [
    {
      "id": 42,
      "email": "user@example.com",
      "timezone": "America/New_York",
      "hour": 9,
      "day_of_week": 1,
      "filters": {"countries": ["United States"]},
      "template": "weekly_digest",
      "active": true,
      "created_at": "2025-11-20T10:00:00Z",
      "updated_at": "2025-11-20T10:00:00Z",
      "last_run": "2025-11-25T14:00:00Z",
      "next_run": "2025-12-02T14:00:00Z",
      "failure_count": 0
    }
  ],
  "limit": 1,
  "used": 1
}
```

**TypeScript Example:**
```typescript
interface Schedule {
  id: number;
  email: string;
  timezone: string;
  hour: number;
  day_of_week: number;
  filters: Record<string, any>;
  template: string;
  active: boolean;
  created_at: string;
  updated_at: string;
  last_run: string | null;
  next_run: string | null;
  failure_count: number;
}

async function listSchedules(): Promise<{schedules: Schedule[], limit: number, used: number}> {
  const response = await fetch('/api/reports/weekly/schedules', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  return response.json();
}
```

---

### 3. Get Schedule Status

**Request:**
```
GET /api/reports/weekly/<schedule_id>/status
Authorization: Bearer <jwt_token>
```

**Response (200):**
```json
{
  "id": 42,
  "email": "user@example.com",
  "timezone": "America/New_York",
  "hour": 9,
  "day_of_week": 1,
  "filters": {"countries": ["United States"]},
  "active": true,
  "last_run": "2025-11-25T14:00:00Z",
  "next_run": "2025-12-02T14:00:00Z",
  "failure_count": 0
}
```

**Errors:**
- `404`: Schedule not found or not owned by user

---

### 4. Deactivate Schedule

**Request:**
```
DELETE /api/reports/weekly/<schedule_id>
Authorization: Bearer <jwt_token>
```

**Response (200):**
```json
{
  "message": "Schedule deactivated"
}
```

**Errors:**
- `404`: Schedule not found or not owned by user

**TypeScript Example:**
```typescript
async function deleteSchedule(scheduleId: number): Promise<void> {
  const response = await fetch(`/api/reports/weekly/${scheduleId}`, {
    method: 'DELETE',
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  if (!response.ok) {
    throw new Error('Failed to delete schedule');
  }
}
```

---

## UI Component Examples

### Schedule Creation Form

```tsx
import React, { useState } from 'react';

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Paris',
  'Asia/Tokyo',
  'Asia/Karachi',
  'Australia/Sydney'
];

export function ScheduleForm() {
  const [timezone, setTimezone] = useState('America/New_York');
  const [hour, setHour] = useState(9);
  const [dayOfWeek, setDayOfWeek] = useState(1);
  const [countries, setCountries] = useState<string[]>([]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    try {
      const result = await createSchedule({
        timezone,
        hour,
        day_of_week: dayOfWeek,
        filters: countries.length > 0 ? { countries } : undefined
      });
      
      alert(`Schedule created! Next digest: ${new Date(result.next_run).toLocaleString()}`);
    } catch (error) {
      alert(error.message);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <div>
        <label>Timezone</label>
        <select value={timezone} onChange={e => setTimezone(e.target.value)}>
          {TIMEZONES.map(tz => <option key={tz} value={tz}>{tz}</option>)}
        </select>
      </div>
      
      <div>
        <label>Day of Week</label>
        <select value={dayOfWeek} onChange={e => setDayOfWeek(Number(e.target.value))}>
          {DAYS.map((day, i) => <option key={i} value={i}>{day}</option>)}
        </select>
      </div>
      
      <div>
        <label>Time (Hour)</label>
        <input 
          type="number" 
          min="0" 
          max="23" 
          value={hour} 
          onChange={e => setHour(Number(e.target.value))}
        />
      </div>
      
      <div>
        <label>Filter Countries (optional)</label>
        <input 
          type="text" 
          placeholder="United States, Canada" 
          onChange={e => setCountries(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
        />
      </div>
      
      <button type="submit">Create Schedule</button>
    </form>
  );
}
```

### Schedules List Component

```tsx
import React, { useEffect, useState } from 'react';

export function SchedulesList() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [limit, setLimit] = useState(0);

  useEffect(() => {
    loadSchedules();
  }, []);

  const loadSchedules = async () => {
    const data = await listSchedules();
    setSchedules(data.schedules);
    setLimit(data.limit);
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Deactivate this schedule?')) return;
    
    await deleteSchedule(id);
    await loadSchedules();
  };

  return (
    <div>
      <h2>Weekly Digest Schedules ({schedules.length}/{limit})</h2>
      
      {schedules.map(schedule => (
        <div key={schedule.id} style={{ border: '1px solid #ccc', padding: '10px', margin: '10px 0' }}>
          <div>
            <strong>{schedule.active ? '✅' : '❌'}</strong> {DAYS[schedule.day_of_week]}s at {schedule.hour}:00 ({schedule.timezone})
          </div>
          <div>Next: {schedule.next_run ? new Date(schedule.next_run).toLocaleString() : 'N/A'}</div>
          <div>Last: {schedule.last_run ? new Date(schedule.last_run).toLocaleString() : 'Never'}</div>
          {schedule.failure_count > 0 && (
            <div style={{ color: 'red' }}>⚠️ {schedule.failure_count} consecutive failures</div>
          )}
          <button onClick={() => handleDelete(schedule.id)}>Deactivate</button>
        </div>
      ))}
    </div>
  );
}
```

---

## Plan Limits

| Plan | Weekly Schedules | PDF Exports/Month |
|------|------------------|-------------------|
| FREE | 0 (blocked) | 1 |
| PRO | 1 | 10 |
| BUSINESS | 3 | Unlimited |
| ENTERPRISE | Unlimited | Unlimited |

---

## Testing Checklist

- [ ] Create schedule with valid timezone/hour/day_of_week
- [ ] Verify 429 error when creating beyond plan limit
- [ ] List schedules shows active and inactive
- [ ] Get status returns correct next_run in UTC
- [ ] Delete schedule sets active=false
- [ ] Frontend displays next_run in user's local time
- [ ] Timezone picker uses IANA timezones
- [ ] Filter builder sends valid JSONB structure

---

## Notes

- **Scheduler runs in-app**: APScheduler in Flask process (no external Railway cron needed)
- **Daily check at 6am UTC**: Processes all schedules where `next_run <= NOW`
- **Email delivery**: Via Brevo with PDF attachment
- **Failure handling**: Auto-disables after 5 consecutive email send failures
- **Timezone conversion**: `next_run` stored in UTC, converted from user's local timezone
- **JSONB filters**: Flexible query without schema changes

---

## Support

- API docs: See main README.md
- Plan upgrades: /settings/billing
- Questions: support@zikarisk.com
