# SLA Mapper - Quick Reference

## TL;DR
✅ **Support level → SLA mapping** with structured logging  
✅ **4 tiers**: FREE (48h) → PRO (24h) → BUSINESS (24h) → ENTERPRISE (4h)  
✅ **Breach detection** and automated logging  
✅ **Zero dependencies** (uses stdlib datetime + logging)

---

## Usage

### Get SLA for Plan
```python
from sla_mapper import get_sla_for_plan, format_sla_summary

# Get full SLA definition
sla = get_sla_for_plan('BUSINESS')
print(sla['response_time_hours'])  # 24
print(sla['priority'])              # high
print(sla['channels'])              # ['email', 'chat', 'phone']

# Get human-readable summary
summary = format_sla_summary('ENTERPRISE')
print(summary)  
# "Dedicated analyst with 4-hour response, 24/7 coverage (4h response, 24/7) via email, chat, phone, dedicated_slack"
```

### Log Support Request
```python
from sla_mapper import log_support_request

request_id = log_support_request(
    user_email='user@example.com',
    plan='PRO',
    request_type='bug',
    metadata={'subject': 'Chat export broken'}
)
# Logs structured event with SLA deadlines
```

### Check SLA Breach
```python
from sla_mapper import check_sla_breach
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
result = check_sla_breach(
    request_id='req-123',
    created_at=now - timedelta(hours=30),
    responded_at=now,
    plan='PRO'
)
print(result['response_breach'])  # True (30h > 24h SLA)
```

---

## SLA Tiers

| Plan | Response | Resolution | Priority | Channels | Coverage |
|------|----------|------------|----------|----------|----------|
| FREE | 48h | 5d | low | email | Business hours |
| PRO | 24h | 3d | normal | email, chat | Business hours |
| BUSINESS | 24h | 2d | high | email, chat, phone | 24/7 |
| ENTERPRISE | 4h | 1d | critical | email, chat, phone, slack | 24/7 |

---

## Integration (main.py)

### Step 1: Import
```python
# Add after logging setup in main.py
from sla_mapper import get_sla_for_plan, format_sla_summary
```

### Step 2: Add to /auth/status Response
```python
return jsonify({
    "email": email,
    "plan": plan_name,
    "support_level": format_sla_summary(plan_name),  # ADD THIS
    "usage": {...}
})
```

### Step 3: Log SLA on Login
```python
# After successful auth
sla = get_sla_for_plan(plan_name)
if sla:
    logger.info(
        "[sla] User authenticated",
        extra={
            'event': 'user_login',
            'user_email': email,
            'plan': plan_name,
            'support_level': sla['support_level'],
            'response_sla_hours': sla['response_time_hours'],
            'priority': sla['priority']
        }
    )
```

---

## Demo

```bash
python demo_sla_mapper.py
```

Output:
- SLA mappings for all plans
- Support request logging examples
- Breach detection scenarios
- Integration patterns

---

## Files

- `sla_mapper.py` - Core implementation
- `demo_sla_mapper.py` - Demo script
- `SLA_IMPLEMENTATION_COMPLETE.md` - Full documentation
- `SLA_QUICK_REFERENCE.md` - This file

---

## Monitoring

### Log Query (Datadog/Splunk)
```
source:sentinel logger:sla_mapper message:"SLA breach detected"
| stats count by plan
```

### Alert Rule
```yaml
alert: enterprise_sla_breach
condition: plan:ENTERPRISE AND message:"SLA breach detected"
action: page:on-call-support
```

---

## Next Steps

1. ✅ Review `demo_sla_mapper.py` output
2. ⚠️ Integrate into `/auth/status` endpoint
3. ⚠️ Add SLA context to error handlers
4. ⚠️ Set up log aggregation alerts
5. ⚠️ Build SLA compliance dashboard

---

**Full docs:** `SLA_IMPLEMENTATION_COMPLETE.md`
