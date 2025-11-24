# Trial API Reference for Frontend

Quick reference for integrating the trial system into your frontend.

## 🔑 Authentication

All endpoints require JWT token in header:
```
Authorization: Bearer <JWT_TOKEN>
```

---

## 📍 Endpoints

### 1. Start Trial
**Endpoint:** `POST /api/user/trial/start`

**Request:**
```json
{
  "plan": "PRO"  // or "BUSINESS"
}
```

**Response (Success):**
```json
{
  "ok": true,
  "trial_started": true,
  "plan": "PRO",
  "trial_ends_at": "2025-12-01T00:00:00Z"
}
```

**Response (Error):**
```json
{
  "error": "User is already on a trial"
}
// Status: 400
```

**Error Cases:**
- User already on trial
- User not on FREE plan
- Invalid plan specified

---

### 2. Get Trial Status
**Endpoint:** `GET /api/user/trial/status`

**Response:**
```json
{
  "ok": true,
  "plan": "PRO",
  "is_trial": true,
  "trial_started_at": "2025-11-24T00:00:00Z",
  "trial_ends_at": "2025-12-01T00:00:00Z",
  "can_start_trial": false,
  "days_remaining": 7,
  "emails_sent": [
    {
      "type": "day_1",
      "sent_at": "2025-11-24T10:00:00Z"
    }
  ]
}
```

**Not on Trial:**
```json
{
  "ok": true,
  "plan": "FREE",
  "is_trial": false,
  "trial_started_at": null,
  "trial_ends_at": null,
  "can_start_trial": true
}
```

---

### 3. Cancel/End Trial
**Endpoint:** `POST /api/user/trial/end`

**Request:**
```json
{
  "convert_to_paid": false  // true to keep plan, false to downgrade to FREE
}
```

**Response (Cancelled):**
```json
{
  "ok": true,
  "trial_expired": true,
  "plan": "FREE"
}
```

**Response (Converted):**
```json
{
  "ok": true,
  "trial_converted": true,
  "plan": "PRO"
}
```

---

## 🎨 UI Components

### Trial CTA Button
```jsx
import { useState } from 'react';
import { useAuth } from '@/context/AuthContext';

function TrialButton({ plan = 'PRO' }) {
  const { token } = useAuth();
  const [loading, setLoading] = useState(false);

  const handleStartTrial = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/user/trial/start', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ plan })
      });

      const data = await response.json();

      if (data.ok) {
        // Success! Redirect to dashboard
        window.location.href = '/dashboard';
      } else {
        alert(data.error);
      }
    } catch (error) {
      alert('Failed to start trial');
    } finally {
      setLoading(false);
    }
  };

  return (
    <button 
      onClick={handleStartTrial}
      disabled={loading}
      className="btn-primary"
    >
      {loading ? 'Starting...' : 'Start 7-Day Free Trial'}
    </button>
  );
}
```

---

### Trial Status Banner
```jsx
import { useEffect, useState } from 'react';
import { useAuth } from '@/context/AuthContext';
import Link from 'next/link';

function TrialBanner() {
  const { token } = useAuth();
  const [trialStatus, setTrialStatus] = useState(null);

  useEffect(() => {
    if (!token) return;

    fetch('/api/user/trial/status', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(res => res.json())
      .then(data => {
        if (data.ok && data.is_trial) {
          setTrialStatus(data);
        }
      })
      .catch(console.error);
  }, [token]);

  if (!trialStatus) return null;

  return (
    <div className="trial-banner">
      <div className="trial-info">
        <strong>{trialStatus.plan} Trial</strong>
        <span>{trialStatus.days_remaining} days remaining</span>
      </div>
      <Link href="/settings/billing" className="trial-link">
        Manage Subscription →
      </Link>
    </div>
  );
}

export default TrialBanner;
```

**CSS:**
```css
.trial-banner {
  background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 12px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-radius: 8px;
  margin-bottom: 16px;
}

.trial-info {
  display: flex;
  gap: 16px;
  align-items: center;
}

.trial-link {
  color: white;
  text-decoration: underline;
  font-weight: 500;
}
```

---

### Trial Cancellation Modal
```jsx
import { useState } from 'react';
import { useAuth } from '@/context/AuthContext';

function CancelTrialModal({ isOpen, onClose }) {
  const { token } = useAuth();
  const [loading, setLoading] = useState(false);

  const handleCancel = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/user/trial/end', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ convert_to_paid: false })
      });

      const data = await response.json();

      if (data.ok) {
        alert('Trial cancelled. You\'re now on the Free plan.');
        window.location.href = '/dashboard';
      } else {
        alert(data.error);
      }
    } catch (error) {
      alert('Failed to cancel trial');
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h2>Cancel Your Trial?</h2>
        <p>
          You'll lose access to PRO features and return to the Free plan.
          You can always upgrade later.
        </p>
        <div className="modal-actions">
          <button onClick={onClose} className="btn-secondary">
            Keep Trial
          </button>
          <button 
            onClick={handleCancel} 
            disabled={loading}
            className="btn-danger"
          >
            {loading ? 'Cancelling...' : 'Cancel Trial'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

---

## 🧪 Testing

### Test User Setup
```bash
# Create test FREE user
curl -X POST https://your-backend.railway.app/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "trial-test@example.com",
    "password": "TestPass123!"
  }'

# Login to get token
curl -X POST https://your-backend.railway.app/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "trial-test@example.com",
    "password": "TestPass123!"
  }'
# Save the JWT token from response
```

### Test Flow
```bash
# 1. Start trial
curl -X POST https://your-backend.railway.app/api/user/trial/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan": "PRO"}'

# 2. Check status
curl -X GET https://your-backend.railway.app/api/user/trial/status \
  -H "Authorization: Bearer $TOKEN"

# 3. Test PRO features (chat, map with 30 days, etc.)
curl -X POST https://your-backend.railway.app/api/sentinel-chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "What threats are in Kyiv?"}'

# 4. Cancel trial
curl -X POST https://your-backend.railway.app/api/user/trial/end \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"convert_to_paid": false}'
```

---

## 🎯 User Flows

### Flow 1: Free User Starts Trial
1. User on FREE plan visits pricing page
2. Clicks "Start 7-Day Free Trial" on PRO card
3. `POST /api/user/trial/start {"plan": "PRO"}`
4. Backend:
   - Updates user to PRO (trial mode)
   - Sends Day 1 welcome email
   - Returns trial info
5. Frontend redirects to dashboard with trial banner

### Flow 2: Trial User Cancels
1. User clicks "Manage Trial" in banner
2. Goes to `/settings/billing`
3. Clicks "Cancel Trial"
4. Confirmation modal appears
5. User confirms cancellation
6. `POST /api/user/trial/end {"convert_to_paid": false}`
7. Backend downgrades to FREE
8. Frontend shows "Trial cancelled" message

### Flow 3: Trial Expires with Payment
1. Day 7 arrives
2. Cron job runs: `POST /api/cron/check-trials`
3. Backend checks if user has payment method (Stripe)
4. If yes: converts to paid (keeps PRO plan)
5. If no: downgrades to FREE
6. Sends email notification

---

## 🚨 Error Handling

### Common Errors

**User already on trial:**
```json
{
  "error": "User is already on a trial"
}
```
**UI Action:** Show message "You're already on a trial. Check your email for details."

---

**User not on FREE plan:**
```json
{
  "error": "Only free users can start trials"
}
```
**UI Action:** Show message "Trials are only available for Free plan users."

---

**Invalid plan:**
```json
{
  "error": "No trial available for INVALID plan"
}
```
**UI Action:** Default to PRO if plan is invalid.

---

## 📊 Analytics Events

Track these events for optimization:

```js
// Trial started
analytics.track('Trial Started', {
  plan: 'PRO',
  trial_ends_at: '2025-12-01T00:00:00Z'
});

// Trial cancelled
analytics.track('Trial Cancelled', {
  plan: 'PRO',
  days_used: 3,
  reason: 'user_initiated'
});

// Trial converted
analytics.track('Trial Converted', {
  plan: 'PRO',
  conversion_day: 7
});

// Trial banner viewed
analytics.track('Trial Banner Viewed', {
  days_remaining: 5
});
```

---

## ✅ Integration Checklist

- [ ] Add "Start Trial" CTA to pricing page
- [ ] Add trial status banner to dashboard/map/chat
- [ ] Add trial management to settings/billing page
- [ ] Add trial cancellation modal
- [ ] Test trial start flow
- [ ] Test trial cancellation flow
- [ ] Test feature access during trial
- [ ] Add analytics tracking
- [ ] Update help docs/FAQ with trial info
- [ ] Test mobile responsive design

---

**Questions?** Check `/TRIAL_STRATEGY.md` for full implementation details.
