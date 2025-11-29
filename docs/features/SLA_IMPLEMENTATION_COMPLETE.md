# Support Level to SLA Mapping - Implementation Complete

## Overview
Complete implementation of support level to SLA (Service Level Agreement) mapping with structured logging for monitoring and tracking support performance across all plan tiers.

## Architecture

### SLA Definitions by Support Level

| Support Level | Plan | Response Time | Resolution Time | Channels | Coverage | Priority |
|---------------|------|---------------|-----------------|----------|----------|----------|
| **email_48h** | FREE | 48 hours (2d) | 120 hours (5d) | email | Business hours | low |
| **email_24h** | PRO | 24 hours (1d) | 72 hours (3d) | email, chat | Business hours | normal |
| **priority_24h** | BUSINESS | 24 hours (1d) | 48 hours (2d) | email, chat, phone | 24/7 | high |
| **analyst_4h** | ENTERPRISE | 4 hours | 24 hours (1d) | email, chat, phone, slack | 24/7 | critical |

### SLA Metrics
- **Response Time**: Maximum time to first human response
- **Resolution Time**: Maximum time to resolve the issue
- **Coverage**: Business hours (M-F 9-5) vs 24/7
- **Priority**: Queue priority (low, normal, high, critical)
- **Escalation**: Management escalation path for breaches

---

## Components

### 1. sla_mapper.py
Core module providing SLA mapping and logging utilities.

**Key Functions:**

#### get_sla_for_plan(plan)
```python
from sla_mapper import get_sla_for_plan

sla = get_sla_for_plan('BUSINESS')
# Returns:
{
    'plan': 'BUSINESS',
    'support_level': 'priority_24h',
    'response_time_hours': 24,
    'resolution_time_hours': 48,
    'channels': ['email', 'chat', 'phone'],
    'priority': 'high',
    'description': 'Priority queue with 24-hour response, phone support',
    'business_hours_only': False,
    'escalation_path': 'manager'
}
```

#### format_sla_summary(plan)
```python
summary = format_sla_summary('ENTERPRISE')
# Returns: "Dedicated analyst with 4-hour response, 24/7 coverage (4h response, 24/7) via email, chat, phone, dedicated_slack"
```

#### log_support_request(user_email, plan, request_type, metadata)
```python
from sla_mapper import log_support_request

request_id = log_support_request(
    user_email='user@example.com',
    plan='PRO',
    request_type='bug',
    metadata={
        'subject': 'Chat export PDF not working',
        'urgency': 'normal'
    }
)
# Logs structured event with SLA deadlines
# Returns: Request UUID for tracking
```

#### check_sla_breach(request_id, created_at, responded_at, resolved_at, plan)
```python
from sla_mapper import check_sla_breach
from datetime import datetime, timezone

result = check_sla_breach(
    request_id='req-123',
    created_at=datetime.now(timezone.utc) - timedelta(hours=30),
    responded_at=datetime.now(timezone.utc),
    plan='PRO'
)
# Returns:
{
    'request_id': 'req-123',
    'plan': 'PRO',
    'support_level': 'email_24h',
    'response_breach': True,  # Responded in 30h, SLA is 24h
    'response_time_hours': 30.0,
    'response_sla_hours': 24,
    'resolution_breach': False
}
```

---

## Integration Points

### 1. Authentication Endpoint (/auth/status)
**Purpose:** Log user login with SLA context for monitoring.

**Implementation:**
```python
# In main.py, after existing imports:
from sla_mapper import get_sla_for_plan, format_sla_summary

# In /auth/status endpoint, add to response JSON:
return jsonify({
    "email": email,
    "plan": plan_name,
    "support_level": format_sla_summary(plan_name),  # ADD THIS
    "usage": {...},
    "limits": {...}
})

# After successful response, log SLA context:
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
            'priority': sla['priority'],
            'channels': sla['channels']
        }
    )
```

**Result:**
```json
{
  "email": "user@example.com",
  "plan": "BUSINESS",
  "support_level": "Priority queue with 24-hour response, phone support (1d response, 24/7) via email, chat, phone",
  "usage": {...}
}
```

### 2. Error Handlers (500, 400)
**Purpose:** Log errors with SLA context to prioritize incident response.

**Implementation:**
```python
@app.errorhandler(500)
def server_error_500(e):
    email = get_logged_in_email() if request else None
    plan = get_user_plan(email) if email else 'FREE'
    sla = get_sla_for_plan(plan)
    
    logger.error(
        "[sla] Server error occurred",
        extra={
            'event': 'server_error',
            'user_email': email,
            'plan': plan,
            'support_level': sla['support_level'] if sla else 'unknown',
            'priority': sla['priority'] if sla else 'low',
            'response_sla_hours': sla['response_time_hours'] if sla else None,
            'error': str(e),
            'traceback': traceback.format_exc()
        }
    )
    
    return jsonify({'error': 'Internal server error'}), 500
```

**Benefit:** Logs show which errors affect high-priority users (ENTERPRISE) vs low-priority (FREE).

### 3. Future: Support Ticket Endpoint
**Purpose:** Track support requests with SLA deadlines.

**Implementation:**
```python
@app.route("/api/support/ticket", methods=["POST"])
@login_required
def create_support_ticket():
    from sla_mapper import log_support_request
    
    email = get_logged_in_email()
    plan = get_user_plan(email)
    data = request.get_json()
    
    # Validate input
    if not data.get('subject') or not data.get('description'):
        return jsonify({'error': 'Subject and description required'}), 400
    
    # Log request with SLA tracking
    request_id = log_support_request(
        user_email=email,
        plan=plan,
        request_type=data.get('type', 'help'),  # help, bug, feature, urgent
        metadata={
            'subject': data.get('subject'),
            'description': data.get('description'),
            'urgency': data.get('urgency', 'normal'),
            'affected_feature': data.get('feature'),
            'user_agent': request.headers.get('User-Agent')
        }
    )
    
    # Store in database (future)
    # insert_support_ticket(request_id, email, data)
    
    # Send notification to support team
    # notify_support_team(request_id, plan)
    
    return jsonify({
        'ok': True,
        'request_id': request_id,
        'message': 'Support ticket created'
    })
```

---

## Structured Logging Examples

### User Login Log
```json
{
  "timestamp": "2025-11-23T18:30:00Z",
  "level": "INFO",
  "logger": "sentinel.main",
  "message": "[sla] User authenticated",
  "event": "user_login",
  "user_email": "cto@bigcorp.com",
  "plan": "ENTERPRISE",
  "support_level": "analyst_4h",
  "response_sla_hours": 4,
  "priority": "critical",
  "channels": ["email", "chat", "phone", "dedicated_slack"]
}
```

### Support Request Log
```json
{
  "timestamp": "2025-11-23T19:15:00Z",
  "level": "INFO",
  "logger": "sla_mapper",
  "message": "[sla_mapper] Support request created",
  "request_id": "8d10cc03-8573-4312-81f9-f23e20ddd18b",
  "user_email": "user@example.com",
  "plan": "BUSINESS",
  "support_level": "priority_24h",
  "request_type": "bug",
  "priority": "high",
  "response_sla_hours": 24,
  "resolution_sla_hours": 48,
  "response_deadline": "2025-11-24T19:15:00Z",
  "resolution_deadline": "2025-11-25T19:15:00Z",
  "channels_available": ["email", "chat", "phone"],
  "business_hours_only": false,
  "metadata": {
    "subject": "Chat export PDF not working"
  }
}
```

### SLA Breach Log
```json
{
  "timestamp": "2025-11-24T22:00:00Z",
  "level": "WARNING",
  "logger": "sla_mapper",
  "message": "[sla_mapper] SLA breach detected",
  "request_id": "req-002",
  "plan": "PRO",
  "support_level": "email_24h",
  "response_breach": true,
  "response_time_hours": 30.0,
  "response_sla_hours": 24,
  "resolution_breach": false,
  "response_deadline": "2025-11-24T19:00:00Z",
  "resolution_deadline": "2025-11-26T19:00:00Z"
}
```

### Server Error Log (with SLA context)
```json
{
  "timestamp": "2025-11-23T20:45:00Z",
  "level": "ERROR",
  "logger": "sentinel.main",
  "message": "[sla] Server error occurred",
  "event": "server_error",
  "user_email": "enterprise@client.com",
  "plan": "ENTERPRISE",
  "support_level": "analyst_4h",
  "priority": "critical",
  "response_sla_hours": 4,
  "error": "Database connection timeout",
  "traceback": "..."
}
```

---

## Monitoring & Alerting

### Log Aggregation (e.g., Datadog, Splunk, ELK)

**Query 1: SLA Breach Rate by Plan**
```
source:sentinel logger:sla_mapper message:"SLA breach detected"
| stats count by plan, support_level
```

**Query 2: High-Priority User Errors**
```
source:sentinel event:server_error priority:critical OR priority:high
| top 10 user_email
```

**Query 3: Average Response Time by Support Level**
```
source:sentinel logger:sla_mapper message:"Support request created"
| stats avg(response_sla_hours) by support_level
```

### Alert Rules

#### Alert 1: ENTERPRISE SLA Breach
```yaml
alert: enterprise_sla_breach
condition: 
  - logger: sla_mapper
  - message: "SLA breach detected"
  - plan: ENTERPRISE
action:
  - page: on-call-support
  - escalate_to: director
  - priority: P1
```

#### Alert 2: Multiple Breaches (any plan)
```yaml
alert: sla_breach_spike
condition:
  - count(message:"SLA breach detected") > 5 in last 1h
action:
  - notify: support-team-slack
  - priority: P2
```

#### Alert 3: Critical User Error
```yaml
alert: critical_user_error
condition:
  - level: ERROR
  - priority: critical
  - event: server_error
action:
  - page: on-call-engineering
  - notify: support-team
  - priority: P1
```

---

## Testing

### Run Demo Script
```bash
cd /home/zika/sentinel_ai_rss
python demo_sla_mapper.py
```

**Output:**
```
SLA MAPPINGS BY PLAN
FREE Plan: Email support with 48-hour response (2d response, business hours) via email
PRO Plan: Email and chat support with 24-hour response (1d response, business hours) via email, chat
BUSINESS Plan: Priority queue with 24-hour response, phone support (1d response, 24/7) via email, chat, phone
ENTERPRISE Plan: Dedicated analyst with 4-hour response, 24/7 coverage (4h response, 24/7) via email, chat, phone, dedicated_slack

SUPPORT REQUEST LOGGING DEMO
📧 Creating support request for FREE user
   Request ID: 4c2f8d3c-41a5-4ffc-ae0e-f32568408d23
...

SLA BREACH CHECKING DEMO
✅ Scenario 1: FREE plan - Responded in 36h (within SLA)
❌ Scenario 2: PRO plan - Responded in 30h (breached SLA)
...
```

### Unit Tests
```python
# tests/test_sla_mapper.py
import pytest
from sla_mapper import get_sla_for_plan, check_sla_breach, format_sla_summary
from datetime import datetime, timedelta, timezone

def test_get_sla_for_plan_free():
    sla = get_sla_for_plan('FREE')
    assert sla['support_level'] == 'email_48h'
    assert sla['response_time_hours'] == 48
    assert sla['priority'] == 'low'

def test_get_sla_for_plan_enterprise():
    sla = get_sla_for_plan('ENTERPRISE')
    assert sla['support_level'] == 'analyst_4h'
    assert sla['response_time_hours'] == 4
    assert sla['priority'] == 'critical'
    assert 'dedicated_slack' in sla['channels']

def test_format_sla_summary():
    summary = format_sla_summary('BUSINESS')
    assert 'Priority queue' in summary
    assert '24/7' in summary
    assert 'phone' in summary

def test_sla_breach_detection():
    now = datetime.now(timezone.utc)
    
    # Within SLA
    result = check_sla_breach(
        'req-1',
        created_at=now - timedelta(hours=20),
        responded_at=now,
        plan='PRO'  # 24h SLA
    )
    assert result['response_breach'] == False
    
    # Breached SLA
    result = check_sla_breach(
        'req-2',
        created_at=now - timedelta(hours=30),
        responded_at=now,
        plan='PRO'  # 24h SLA
    )
    assert result['response_breach'] == True

def test_unknown_plan():
    sla = get_sla_for_plan('UNKNOWN_PLAN')
    assert sla is None
```

---

## Dashboard Visualization

### Support Performance Dashboard (Example: Grafana)

**Panel 1: SLA Compliance Rate**
```sql
-- Query: Percentage of requests within SLA by plan
SELECT 
  plan,
  COUNT(*) FILTER (WHERE response_breach = false) * 100.0 / COUNT(*) as compliance_rate
FROM support_requests
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY plan
ORDER BY compliance_rate DESC
```

**Panel 2: Average Response Time by Support Level**
```sql
SELECT 
  support_level,
  AVG(response_time_hours) as avg_response_hours,
  response_sla_hours as sla_hours
FROM support_requests
WHERE responded_at IS NOT NULL
GROUP BY support_level, response_sla_hours
```

**Panel 3: Breach Alerts Timeline**
```
-- Time series of SLA breaches
SELECT 
  DATE_TRUNC('hour', timestamp) as hour,
  COUNT(*) as breach_count,
  support_level
FROM logs
WHERE message LIKE '%SLA breach detected%'
GROUP BY hour, support_level
ORDER BY hour DESC
```

---

## Business Impact

### SLA Metrics by Plan Tier

| Metric | FREE | PRO | BUSINESS | ENTERPRISE |
|--------|------|-----|----------|------------|
| **Response SLA** | 48h | 24h | 24h | 4h |
| **Resolution SLA** | 5 days | 3 days | 2 days | 1 day |
| **Channels** | Email | Email, Chat | Email, Chat, Phone | Email, Chat, Phone, Slack |
| **Coverage** | Business hours | Business hours | 24/7 | 24/7 |
| **Escalation** | None | None | Manager | Director |
| **Priority** | Low | Normal | High | Critical |

### Cost-to-Serve Analysis
- **FREE**: $0 cost-to-serve (email only, low priority)
- **PRO**: ~$50/month support overhead (chat support added)
- **BUSINESS**: ~$150/month (phone support, 24/7 coverage)
- **ENTERPRISE**: ~$500/month (dedicated analyst, Slack, escalation)

### ROI from SLA Tracking
- **Visibility**: Know which users need immediate attention
- **Prioritization**: Auto-route critical issues (ENTERPRISE) to top of queue
- **Compliance**: Track SLA adherence for contract renewals
- **Optimization**: Identify bottlenecks (avg response time per tier)
- **Upsell**: Prove value of premium support ("PRO users waited 30h, ENTERPRISE 2h")

---

## Future Enhancements

### Phase 2: Database Storage
```sql
CREATE TABLE support_requests (
    request_id UUID PRIMARY KEY,
    user_email TEXT NOT NULL,
    plan TEXT NOT NULL,
    support_level TEXT NOT NULL,
    request_type TEXT,
    priority TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    responded_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    response_sla_hours INTEGER,
    resolution_sla_hours INTEGER,
    response_breach BOOLEAN,
    resolution_breach BOOLEAN,
    metadata JSONB,
    INDEX idx_support_plan (plan),
    INDEX idx_support_created (created_at),
    INDEX idx_support_breach (response_breach, resolution_breach)
);
```

### Phase 3: Auto-Escalation
```python
def check_and_escalate_breaches():
    """Background job to auto-escalate SLA breaches."""
    breached = query_breached_requests()
    for req in breached:
        sla = get_sla_for_plan(req['plan'])
        if sla['escalation_path']:
            notify_escalation_path(req, sla['escalation_path'])
```

### Phase 4: Customer-Facing SLA Portal
```python
@app.route("/api/support/tickets", methods=["GET"])
@login_required
def list_support_tickets():
    """Show user their support tickets with SLA status."""
    email = get_logged_in_email()
    tickets = query_user_tickets(email)
    
    for ticket in tickets:
        sla_status = check_sla_breach(
            ticket['request_id'],
            ticket['created_at'],
            ticket['responded_at'],
            ticket['resolved_at'],
            ticket['plan']
        )
        ticket['sla_status'] = sla_status
    
    return jsonify({'tickets': tickets})
```

---

## Summary

### ✅ What Was Implemented
- **SLA definitions** for all 4 plan tiers (FREE, PRO, BUSINESS, ENTERPRISE)
- **Structured logging** with SLA context (response time, priority, channels)
- **Breach detection** to track when SLAs are violated
- **Demo script** to visualize SLA mappings and test functionality
- **Integration patterns** for main.py endpoints

### 📊 Key Metrics
- **Response SLAs**: 48h (FREE) → 4h (ENTERPRISE)
- **Priority levels**: low → critical
- **Coverage**: Business hours (FREE/PRO) → 24/7 (BUSINESS/ENTERPRISE)
- **Channels**: email → email + chat + phone + slack

### 🎯 Next Steps
1. Integrate SLA logging into `/auth/status` endpoint
2. Add SLA context to error handlers (500, 400)
3. Create support ticket endpoint with SLA tracking
4. Set up log aggregation alerts for SLA breaches
5. Build dashboard to monitor SLA compliance

### 📂 Files Created
- `sla_mapper.py` - Core SLA mapping and logging utilities
- `demo_sla_mapper.py` - Demonstration script with examples
- `SLA_IMPLEMENTATION_COMPLETE.md` - This documentation
- `SLA_INTEGRATION_PATCH.txt` - Integration guide for main.py

---

**Questions?** Review `demo_sla_mapper.py` for usage examples or check structured logs for SLA events.
