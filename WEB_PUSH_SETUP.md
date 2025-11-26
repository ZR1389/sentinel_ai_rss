# Web Push Notifications - Setup & Frontend Integration

## Overview

Your app has **Web Push notifications** fully implemented:
- Backend: `webpush_endpoints.py` (4 routes), `webpush_send.py` (VAPID sender), `push_dispatcher.py` (mobile stub)
- Plan-gated: **Paid plans only** (PRO/BUSINESS/ENTERPRISE)
- Uses: Web Push API with VAPID (browser notifications)
- Status: **Ready to use** (needs env vars + frontend integration)

---

## Backend Status

### ✅ What's Working
- **4 API Endpoints** (already registered in `main.py`):
  - `GET /push_status` - Check if user has active subscriptions
  - `POST /subscribe_push` - Register browser subscription
  - `POST /unsubscribe_push` - Remove subscription(s)
  - `POST /push/test` - Send test notification to all user's browsers
- **Plan Enforcement**: Only paid users can subscribe
- **Auto-cleanup**: Expired/invalid endpoints (404/410) removed automatically
- **Multi-device**: Supports multiple browsers per user

### 🔧 Required Configuration

**Environment Variables (Railway):**
```bash
# Required
VAPID_PRIVATE_KEY=<your-vapid-private-key>
VAPID_PUBLIC_KEY=<your-vapid-public-key>
VAPID_EMAIL=mailto:security@zikarisk.com

# Optional
PUSH_ENABLED=true  # default: false
```

**Generate VAPID Keys:**
```bash
# Install pywebpush if not already in requirements.txt
pip install pywebpush

# Generate keys
python3 -c "from pywebpush import vapid_key; keys = vapid_key.generate(); print('VAPID_PRIVATE_KEY=' + keys['private']); print('VAPID_PUBLIC_KEY=' + keys['public'])"
```

**Run Migration:**
```bash
railway run psql $DATABASE_URL -f migrate_web_push_subscriptions.sql
```

---

## Frontend Integration

### 1. Service Worker Setup

Create `public/service-worker.js`:
```javascript
// Service worker for Web Push notifications
self.addEventListener('push', function(event) {
  const data = event.data ? event.data.json() : {};
  
  const title = data.title || 'Sentinel AI';
  const options = {
    body: data.body || 'New notification',
    icon: '/logo192.png',
    badge: '/badge.png',
    data: {
      url: data.url || '/dashboard'
    },
    tag: 'sentinel-notification',
    requireInteraction: false
  };
  
  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  
  const url = event.notification.data?.url || '/dashboard';
  
  event.waitUntil(
    clients.openWindow(url)
  );
});
```

**Register in `index.html`:**
```html
<script>
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js')
      .then(reg => console.log('Service Worker registered'))
      .catch(err => console.error('Service Worker registration failed:', err));
  }
</script>
```

---

### 2. Push Subscription Manager (React/TypeScript)

```typescript
// utils/pushNotifications.ts
const API_BASE = process.env.REACT_APP_API_URL || 'https://your-api.railway.app';
const VAPID_PUBLIC_KEY = process.env.REACT_APP_VAPID_PUBLIC_KEY; // Set this in .env

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding)
    .replace(/\-/g, '+')
    .replace(/_/g, '/');
  
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export async function subscribeToPush(token: string): Promise<boolean> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    console.warn('Push notifications not supported');
    return false;
  }

  if (!VAPID_PUBLIC_KEY) {
    console.error('VAPID_PUBLIC_KEY not configured');
    return false;
  }

  try {
    // Get service worker registration
    const registration = await navigator.serviceWorker.ready;
    
    // Check existing subscription
    let subscription = await registration.pushManager.getSubscription();
    
    // Subscribe if not already subscribed
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
      });
    }

    // Send to backend
    const response = await fetch(`${API_BASE}/subscribe_push`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ subscription: subscription.toJSON() })
    });

    if (response.status === 403) {
      const error = await response.json();
      throw new Error(error.error || 'Paid plan required');
    }

    if (!response.ok) {
      throw new Error('Failed to subscribe');
    }

    return true;
  } catch (error) {
    console.error('Push subscription failed:', error);
    throw error;
  }
}

export async function unsubscribeFromPush(token: string): Promise<boolean> {
  try {
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    
    if (subscription) {
      await subscription.unsubscribe();
      
      // Notify backend
      await fetch(`${API_BASE}/unsubscribe_push`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ endpoint: subscription.endpoint })
      });
    }
    
    return true;
  } catch (error) {
    console.error('Push unsubscribe failed:', error);
    return false;
  }
}

export async function checkPushStatus(token: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/push_status`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    
    if (!response.ok) return false;
    
    const data = await response.json();
    return data.enabled || false;
  } catch {
    return false;
  }
}

export async function sendTestPush(token: string): Promise<{sent: number, removed: number}> {
  const response = await fetch(`${API_BASE}/push/test`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` }
  });
  
  if (!response.ok) {
    throw new Error('Failed to send test notification');
  }
  
  return response.json();
}

export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!('Notification' in window)) {
    throw new Error('Notifications not supported');
  }
  
  if (Notification.permission === 'granted') {
    return 'granted';
  }
  
  if (Notification.permission !== 'denied') {
    return await Notification.requestPermission();
  }
  
  return Notification.permission;
}
```

---

### 3. Settings Component (React)

```tsx
// components/PushNotificationSettings.tsx
import React, { useState, useEffect } from 'react';
import { 
  subscribeToPush, 
  unsubscribeFromPush, 
  checkPushStatus,
  sendTestPush,
  requestNotificationPermission
} from '../utils/pushNotifications';

interface Props {
  token: string;
  userPlan: string;
}

export function PushNotificationSettings({ token, userPlan }: Props) {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [permission, setPermission] = useState<NotificationPermission>('default');
  
  const isPaidPlan = ['PRO', 'BUSINESS', 'ENTERPRISE'].includes(userPlan.toUpperCase());

  useEffect(() => {
    // Check browser support
    if ('Notification' in window) {
      setPermission(Notification.permission);
    }

    // Check backend status
    checkPushStatus(token).then(setEnabled);
  }, [token]);

  const handleToggle = async () => {
    if (!isPaidPlan) {
      alert('Push notifications require a paid plan (PRO or higher)');
      return;
    }

    setLoading(true);
    try {
      if (enabled) {
        await unsubscribeFromPush(token);
        setEnabled(false);
      } else {
        // Request permission first
        const perm = await requestNotificationPermission();
        setPermission(perm);
        
        if (perm !== 'granted') {
          alert('Notification permission denied. Please enable in browser settings.');
          return;
        }

        await subscribeToPush(token);
        setEnabled(true);
      }
    } catch (error: any) {
      alert(error.message || 'Failed to update push settings');
    } finally {
      setLoading(false);
    }
  };

  const handleTest = async () => {
    try {
      const result = await sendTestPush(token);
      alert(`Test sent! Delivered: ${result.sent}, Cleaned up: ${result.removed}`);
    } catch (error) {
      alert('Test failed. Make sure you have an active subscription.');
    }
  };

  if (!('Notification' in window) || !('serviceWorker' in navigator)) {
    return (
      <div className="alert alert-warning">
        Push notifications not supported in this browser.
      </div>
    );
  }

  return (
    <div className="push-settings">
      <h3>Push Notifications</h3>
      
      {!isPaidPlan && (
        <div className="alert alert-info">
          🔒 Available on PRO, BUSINESS, and ENTERPRISE plans
        </div>
      )}
      
      <div className="form-check form-switch">
        <input
          type="checkbox"
          className="form-check-input"
          checked={enabled}
          onChange={handleToggle}
          disabled={loading || !isPaidPlan}
        />
        <label className="form-check-label">
          Enable browser push notifications
        </label>
      </div>

      {permission === 'denied' && (
        <div className="alert alert-warning mt-2">
          ⚠️ Notifications blocked. Enable in browser settings: Site Settings → Notifications
        </div>
      )}

      {enabled && (
        <button
          className="btn btn-sm btn-outline-primary mt-2"
          onClick={handleTest}
        >
          Send Test Notification
        </button>
      )}

      <small className="text-muted d-block mt-2">
        Browser notifications for threat alerts, digest reminders, and system updates.
      </small>
    </div>
  );
}
```

---

### 4. Environment Variables (.env)

```bash
# Frontend .env
REACT_APP_API_URL=https://your-api.railway.app
REACT_APP_VAPID_PUBLIC_KEY=<your-vapid-public-key>
```

---

## API Endpoints Summary

### GET `/push_status`
Check if user has active subscriptions.

**Response:**
```json
{
  "enabled": true
}
```

---

### POST `/subscribe_push`
Register browser subscription (paid plans only).

**Request:**
```json
{
  "subscription": {
    "endpoint": "https://fcm.googleapis.com/fcm/send/...",
    "keys": {
      "p256dh": "BNcRd...",
      "auth": "tBHI..."
    }
  }
}
```

**Response:**
```json
{
  "ok": true
}
```

**Errors:**
- `403`: "Paid plan required for push notifications."
- `403`: "Push disabled" (if `PUSH_ENABLED=false`)

---

### POST `/unsubscribe_push`
Remove subscription(s).

**Request:**
```json
{
  "endpoint": "https://fcm.googleapis.com/fcm/send/..."  // optional; if omitted, removes all
}
```

**Response:**
```json
{
  "ok": true
}
```

---

### POST `/push/test`
Send test notification to all user's browsers.

**Response:**
```json
{
  "ok": true,
  "sent": 2,
  "removed": 0
}
```

---

## Sending Push Notifications (Backend)

**From anywhere in your backend:**
```python
from webpush_send import send_web_push

# Load user's subscriptions from DB
subscriptions = get_user_push_subscriptions(user_email)

payload = {
    "title": "🚨 High Threat Alert",
    "body": "Terrorism incident detected in New York",
    "url": "/alerts/12345"
}

for sub in subscriptions:
    result = send_web_push(sub, payload)
    if result is False:
        # Subscription expired - remove from DB
        delete_subscription(sub['endpoint'])
```

---

## Testing Checklist

- [ ] Generate VAPID keys and add to Railway env
- [ ] Run `migrate_web_push_subscriptions.sql`
- [ ] Set `PUSH_ENABLED=true` in Railway
- [ ] Add service worker to frontend
- [ ] Implement subscription toggle in settings
- [ ] Test with paid plan user
- [ ] Verify 403 error for free plan users
- [ ] Send test notification via `/push/test`
- [ ] Check auto-cleanup of expired endpoints

---

## Notes

- **Browser Support**: Chrome, Firefox, Edge, Safari 16+
- **HTTPS Required**: Web Push only works on HTTPS (or localhost)
- **Plan Enforcement**: Backend checks `user_has_paid_plan()` before allowing subscriptions
- **Multi-Device**: Users can have subscriptions from multiple browsers/devices
- **Auto-Cleanup**: Invalid endpoints (404/410) automatically removed
- **Payload Size**: Max ~4KB per notification

---

## Troubleshooting

**"Push notifications not working":**
- Check browser console for service worker errors
- Verify VAPID keys in Railway env
- Confirm `PUSH_ENABLED=true`
- Check notification permission (browser settings)

**"403 Paid plan required":**
- User needs PRO/BUSINESS/ENTERPRISE plan
- Check `user_has_paid_plan(email)` returns `True`

**"No notifications received":**
- Check service worker is registered: `chrome://serviceworker-internals`
- Verify subscription exists in `web_push_subscriptions` table
- Test with `/push/test` endpoint
- Check browser notification settings (not blocked)
