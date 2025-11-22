# Thread Management Endpoints Quick Reference

## All 10 Endpoints Implemented ✅

### 1. Create Thread
```
POST /api/chat/threads
Body: { title, investigation_topic, messages[] }
Response: 201 Created
```

### 2. List Threads (with Pagination)
```
GET /api/chat/threads?archived=false&page=1&limit=20
Response: 200 OK
```

### 3. Get Single Thread
```
GET /api/chat/threads/:uuid
Response: 200 OK
```

### 4. Add Messages to Thread
```
POST /api/chat/threads/:uuid/messages
Body: { messages[] }
Response: 201 Created
```

### 5. Update Thread Title
```
PATCH /api/chat/threads/:uuid
Body: { title }
Response: 200 OK
```

### 6. Archive Thread (PRO+)
```
POST /api/chat/threads/:uuid/archive
Response: 200 OK
```

### 7. Unarchive Thread
```
POST /api/chat/threads/:uuid/unarchive
Response: 200 OK
```

### 8. Soft Delete Thread
```
DELETE /api/chat/threads/:uuid
Response: 200 OK (30-day restore window)
```

### 9. Restore Deleted Thread
```
POST /api/chat/threads/:uuid/restore
Response: 200 OK | 410 Gone (expired)
```

### 10. Get Usage Statistics
```
GET /api/chat/threads/usage
Response: 200 OK (comprehensive stats)
```

## Test Commands

```bash
# Set your JWT token
export JWT="your_jwt_token_here"
export API="https://your-backend.up.railway.app"

# 1. Create thread
curl -X POST $API/api/chat/threads \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "London Security Analysis",
    "messages": [
      {"role": "user", "content": "What are current threats?", "timestamp": "2025-11-21T10:00:00Z"},
      {"role": "assistant", "content": "Based on intelligence...", "timestamp": "2025-11-21T10:00:15Z"}
    ]
  }'

# 2. List threads
curl -X GET "$API/api/chat/threads?archived=false&page=1&limit=20" \
  -H "Authorization: Bearer $JWT"

# 3. Get thread (replace UUID)
curl -X GET "$API/api/chat/threads/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer $JWT"

# 4. Add messages (replace UUID)
curl -X POST "$API/api/chat/threads/550e8400-e29b-41d4-a716-446655440000/messages" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Tell me more", "timestamp": "2025-11-21T11:00:00Z"}
    ]
  }'

# 5. Update title (replace UUID)
curl -X PATCH "$API/api/chat/threads/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated Analysis Title"}'

# 6. Archive thread (PRO+ only)
curl -X POST "$API/api/chat/threads/550e8400-e29b-41d4-a716-446655440000/archive" \
  -H "Authorization: Bearer $JWT"

# 7. Unarchive thread
curl -X POST "$API/api/chat/threads/550e8400-e29b-41d4-a716-446655440000/unarchive" \
  -H "Authorization: Bearer $JWT"

# 8. Delete thread (soft)
curl -X DELETE "$API/api/chat/threads/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer $JWT"

# 9. Restore deleted thread
curl -X POST "$API/api/chat/threads/550e8400-e29b-41d4-a716-446655440000/restore" \
  -H "Authorization: Bearer $JWT"

# 10. Get usage stats
curl -X GET "$API/api/chat/threads/usage" \
  -H "Authorization: Bearer $JWT"
```

## Expected Error Responses

### FREE User - Thread Limit
```json
{
  "error": "Max active threads (5) reached",
  "feature_locked": true,
  "required_plan": "PRO",
  "can_archive": false,
  "suggestion": "Delete an old thread or upgrade to PRO for 50 threads + archiving."
}
```

### FREE User - Per-Thread Message Limit
```json
{
  "error": "Thread has reached its 3-message limit",
  "feature_locked": true,
  "thread_full": true,
  "usage": {
    "thread_messages": 3,
    "thread_message_limit": 3,
    "active_threads": 2,
    "threads_limit": 5
  },
  "suggestion": "Save this thread and start a new conversation, or upgrade to PRO for 50 messages per thread."
}
```

### FREE User - Cannot Archive
```json
{
  "error": "Thread archiving requires PRO plan or higher",
  "feature_locked": true,
  "required_plan": "PRO"
}
```

### PRO User - Monthly Quota Exceeded
```json
{
  "error": "Monthly message quota (500) exceeded",
  "feature_locked": true
}
```

### Restore Expired Thread
```json
{
  "error": "Thread permanently deleted after 30-day grace period"
}
```

## Frontend Integration Checklist

- [ ] Store JWT token in secure storage
- [ ] Implement thread list with pagination
- [ ] Show usage stats (X/Y threads, X/Y messages)
- [ ] Display upgrade CTA when limits reached
- [ ] Handle 403 errors with feature_locked flag
- [ ] Implement archive/unarchive UI (PRO+ only)
- [ ] Show "Thread Full" badge when at limit
- [ ] Implement soft delete with restore option
- [ ] Show countdown for restore window (30 days)
- [ ] Poll /usage endpoint for real-time stats
- [ ] Cache plan limits on login
- [ ] Show monthly quota progress bar (PRO+)

## Migration Status

⚠️ **Migration 003 NOT YET APPLIED**

Before testing, run:
```bash
DATABASE_PUBLIC_URL="your_db_url" python - <<'PY'
import os, psycopg2

DB = os.environ['DATABASE_PUBLIC_URL']
conn = psycopg2.connect(DB)
cur = conn.cursor()

with open('migrations/003_chat_threads_archive.sql', 'r') as f:
    sql = f.read()
    cur.execute(sql)

conn.commit()
cur.close()
conn.close()
print("✅ Migration 003 applied")
PY
```
