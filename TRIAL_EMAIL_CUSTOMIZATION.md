# Trial Email Template Customization Guide

Quick guide for customizing trial reminder emails in `utils/trial_reminder.py`.

---

## 📧 Email Template Structure

Each email template has:
- **`subject`** - Email subject line
- **`html`** - HTML email body with placeholders

### Available Placeholders

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{name}` | User's name (extracted from email) | "John" |
| `{plan}` | Plan name | "PRO" |
| `{trial_ends_date}` | Trial end date | "December 1, 2025" |
| `{app_url}` | Frontend URL | "https://sentinel-ai.app" |
| `{chat_messages}` | Chat message limit | "500" |
| `{map_days}` | Map historical days | "30" |
| `{saved_searches}` | Saved search limit | "3" |
| `{trip_destinations}` | Trip planner limit | "5" |
| `{price}` | Plan monthly price | "79" |

---

## 🎨 Customization Examples

### Change Subject Lines

**Location:** `utils/trial_reminder.py` → `TRIAL_EMAIL_TEMPLATES`

```python
'day_1': {
    'subject': 'Welcome to Your 7-Day Trial! 🚀',  # Change this
    'html': ...
}
```

**Alternatives:**
- "Your Sentinel AI Trial Starts Now"
- "Get Started with Your PRO Trial"
- "7 Days of Premium Features Unlocked"

---

### Customize Email Body

**Add new sections:**

```python
'day_1': {
    'subject': 'Welcome to Your 7-Day Trial! 🚀',
    'html': """
    <h2>Welcome to Sentinel AI {plan}!</h2>
    <p>Hi {name},</p>
    
    <!-- NEW: Add personalized greeting -->
    <p>We're excited to have you on board!</p>
    
    <!-- EXISTING: Feature overview -->
    <ul>
        <li><strong>Explore the Threat Map</strong>: View real-time global threats</li>
        <li><strong>Chat with Sentinel AI</strong>: Ask about any location</li>
        <li><strong>Set up Alerts</strong>: Get notified about threats</li>
    </ul>
    
    <!-- NEW: Add testimonial -->
    <blockquote>
        "Sentinel AI helped me plan a safe trip to Eastern Europe" 
        - Sarah M., Travel Blogger
    </blockquote>
    
    <p>Your trial ends on {trial_ends_date}.</p>
    <p>Questions? Reply to this email.</p>
    """
}
```

---

### Add CTA Buttons

**Styled button example:**

```python
'day_3': {
    'subject': 'Pro Tip: Set Up Location Monitoring 📍',
    'html': """
    <h2>Make the Most of Your Trial</h2>
    <p>Hi {name},</p>
    
    <h3>🔔 Saved Searches & Monitoring Alerts</h3>
    <p>Create up to {saved_searches} custom searches...</p>
    
    <!-- CTA Button -->
    <div style="text-align: center; margin: 30px 0;">
        <a href="{app_url}/monitoring" 
           style="background: #007bff; 
                  color: white; 
                  padding: 15px 30px; 
                  text-decoration: none; 
                  border-radius: 5px;
                  display: inline-block;
                  font-weight: bold;">
            Set Up Monitoring →
        </a>
    </div>
    
    <p>Trial ends: {trial_ends_date}</p>
    """
}
```

---

### Adjust Email Timing

**Location:** `utils/trial_reminder.py` → `check_and_send_trial_reminders()`

```python
# Current schedule: Days 1, 3, 5, 6
days_elapsed = (now - trial_started).days

if days_elapsed == 1:
    reminders_to_send.append(1)
elif days_elapsed == 3:
    reminders_to_send.append(3)
elif days_elapsed == 5:
    reminders_to_send.append(5)
elif days_elapsed == 6:
    reminders_to_send.append(6)
```

**Change to Days 1, 2, 4, 6:**

```python
if days_elapsed == 1:
    reminders_to_send.append(1)
elif days_elapsed == 2:  # Changed from 3
    reminders_to_send.append(2)  # Update template key too
elif days_elapsed == 4:  # Changed from 5
    reminders_to_send.append(4)  # Update template key too
elif days_elapsed == 6:
    reminders_to_send.append(6)
```

---

### Add New Email (Day 7)

**Step 1:** Add template to `TRIAL_EMAIL_TEMPLATES`:

```python
'day_7': {
    'subject': 'Your Trial Has Ended',
    'html': """
    <h2>Thank You for Trying Sentinel AI</h2>
    <p>Hi {name},</p>
    <p>Your 7-day {plan} trial has ended.</p>
    <p>We hope you found it valuable!</p>
    <p>To continue with full access:</p>
    <a href="{app_url}/settings/billing">Subscribe Now →</a>
    <p>Or downgrade to our Free plan anytime.</p>
    """
}
```

**Step 2:** Add to schedule in `check_and_send_trial_reminders()`:

```python
if days_elapsed == 7:
    reminders_to_send.append(7)
```

---

## 🎨 Design Best Practices

### 1. Keep It Simple
- Use clean HTML (tables for layout in email clients)
- Avoid complex CSS (many email clients strip it)
- Test in multiple email clients (Gmail, Outlook, Apple Mail)

### 2. Mobile-Friendly
```html
<!-- Use max-width for mobile -->
<div style="max-width: 600px; margin: 0 auto; padding: 20px;">
    Your content here
</div>

<!-- Use large touch targets for buttons -->
<a href="..." style="padding: 15px 30px; font-size: 16px;">
    Button Text
</a>
```

### 3. Clear CTAs
- One primary CTA per email
- Use action-oriented text ("Set Up Alerts" not "Click Here")
- Make buttons visually distinct

### 4. Personalization
```python
# In send_trial_reminder(), enhance name extraction:
def _get_user_name(email):
    """Extract name from email or database."""
    # Try to get from database first
    try:
        with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT name FROM users WHERE email=%s", (email,))
            row = cur.fetchone()
            if row and row['name']:
                return row['name']
    except:
        pass
    
    # Fallback: parse from email
    return email.split('@')[0].capitalize()
```

---

## 🧪 Testing Templates

### Preview in Browser

Add this to `send_trial_reminder()` for testing:

```python
def send_trial_reminder(...):
    # ... existing code ...
    
    html_body = _render_email(template_key, context)
    
    # Save to file for preview
    if os.getenv('DEBUG') == 'true':
        with open(f'email_preview_{template_key}.html', 'w') as f:
            f.write(html_body)
        logger.info(f"Email preview saved to email_preview_{template_key}.html")
    
    # ... continue with send_email ...
```

Then open in browser to preview.

---

### Send Test Email

```python
# In Python console or test script
from utils.trial_reminder import send_trial_reminder
from datetime import datetime, timedelta

# Send Day 1 email to yourself
send_trial_reminder(
    user_id=1,
    user_email='your-email@example.com',
    plan='PRO',
    trial_day=1,
    trial_ends_at=datetime.utcnow() + timedelta(days=7)
)
```

---

## 📊 A/B Testing

To test different versions:

1. **Create variant templates:**
```python
TRIAL_EMAIL_TEMPLATES = {
    'day_1_v1': {  # Control
        'subject': 'Welcome to Your Trial',
        'html': '...'
    },
    'day_1_v2': {  # Test variant
        'subject': 'Your PRO Trial Starts Now',
        'html': '...'
    }
}
```

2. **Randomly assign variant:**
```python
def send_trial_reminder(...):
    # Randomly pick variant
    import random
    variant = 'v1' if random.random() < 0.5 else 'v2'
    template_key = f'day_{trial_day}_{variant}'
    
    # Log variant for tracking
    logger.info(f"Sending email variant {variant} to {user_email}")
    
    # Continue with send...
```

3. **Track results:**
```sql
ALTER TABLE trial_emails_sent ADD COLUMN variant VARCHAR(10);
```

---

## ✅ Customization Checklist

- [ ] Update subject lines for brand voice
- [ ] Add company logo/branding
- [ ] Customize CTA button styles
- [ ] Add social proof (testimonials, stats)
- [ ] Test in Gmail, Outlook, Apple Mail
- [ ] Preview on mobile device
- [ ] A/B test subject lines
- [ ] Add unsubscribe link (if required)
- [ ] Include support contact
- [ ] Proofread for typos/grammar

---

## 🚀 Deploy Changes

After customizing:

1. **Test locally:**
```bash
python -c "from utils.trial_reminder import check_and_send_trial_reminders; check_and_send_trial_reminders()"
```

2. **Deploy to Railway:**
```bash
git add utils/trial_reminder.py
git commit -m "Customize trial email templates"
git push origin main
railway up
```

3. **Verify in production:**
```bash
curl -X POST \
  -H "X-Cron-Secret: $CRON_SECRET" \
  https://your-backend.railway.app/api/cron/trial-reminders
```

---

**Happy customizing! 🎨**
