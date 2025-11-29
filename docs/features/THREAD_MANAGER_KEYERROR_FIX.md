# Thread Manager KeyError Fix

## Issue
**Error**: `KeyError(0)` on `/api/chat/threads/usage` endpoint causing 500 responses.

**Root Cause**: `utils/thread_manager.py` was using tuple-style index access `fetchone()[0]` on `RealDictCursor` results, which return dictionaries, not tuples.

## Error Pattern
```python
# ❌ WRONG - Causes KeyError(0) with RealDictCursor
cur.execute("SELECT get_monthly_message_count(%s)", (user_id,))
monthly_used = cur.fetchone()[0]

# ✅ CORRECT - Use dict key access
cur.execute("SELECT get_monthly_message_count(%s) as count", (user_id,))
monthly_used = cur.fetchone()['count']
```

## Railway Logs Evidence
```
2025-11-22T17:26:20.479165Z [ERRO] event="chat_threads_usage error: %s" 
positional_args=["KeyError(0)"]

2025-11-22T18:35:19.690362Z [ERRO] event="chat_threads_usage error: %s" 
positional_args=["KeyError(0)"]
```

## Fixed Locations
All 3 instances in `utils/thread_manager.py`:

1. **Line 61** (`get_usage_stats`): Monthly message count query
2. **Line 109** (`create_thread`): Monthly quota validation
3. **Line 320** (`add_messages`): Monthly quota check before insert

## Changes Made
```python
# Function: get_usage_stats (line 59-61)
- cur.execute("SELECT get_monthly_message_count(%s)", (user_id,))
- monthly_used = cur.fetchone()[0]
+ cur.execute("SELECT get_monthly_message_count(%s) as count", (user_id,))
+ monthly_used = cur.fetchone()['count']

# Function: create_thread (line 107-109)
- cur.execute("SELECT get_monthly_message_count(%s)", (user_id,))
- monthly_used = cur.fetchone()[0]
+ cur.execute("SELECT get_monthly_message_count(%s) as count", (user_id,))
+ monthly_used = cur.fetchone()['count']

# Function: add_messages (line 318-320)
- cur.execute("SELECT get_monthly_message_count(%s)", (user_id,))
- monthly_used = cur.fetchone()[0]
+ cur.execute("SELECT get_monthly_message_count(%s) as count", (user_id,))
+ monthly_used = cur.fetchone()['count']
```

## Technical Details

### Why This Happened
When using `psycopg2.extras.RealDictCursor`, query results are returned as dictionaries where:
- Column names become keys
- Column values become values

For PL/pgSQL function calls like `SELECT get_monthly_message_count(123)`:
- Without alias: Result key is the full function call string (hard to access)
- With alias: Result key is the alias name (easy dict access)

### Cursor Behavior Comparison
```python
# Regular cursor (cursor_factory not specified)
cur.execute("SELECT get_monthly_message_count(1)")
result = cur.fetchone()  # Returns: (42,)
count = result[0]        # ✅ Works

# RealDictCursor
cur.execute("SELECT get_monthly_message_count(1)")
result = cur.fetchone()  # Returns: {'get_monthly_message_count': 42}
count = result[0]        # ❌ KeyError(0) - no index access

# RealDictCursor with alias
cur.execute("SELECT get_monthly_message_count(1) as count")
result = cur.fetchone()  # Returns: {'count': 42}
count = result['count']  # ✅ Works
```

## Testing
After deployment, verify:

1. **Usage Endpoint**: `GET /api/chat/threads/usage`
   - Should return 200 with usage statistics
   - No more KeyError(0) in Railway logs

2. **Thread Creation**: `POST /api/chat/threads`
   - Monthly quota validation should work
   - Users near monthly limit should see proper error

3. **Add Messages**: `POST /api/chat/threads/:uuid/messages`
   - Monthly quota check should work
   - Proper error when exceeding monthly limit

## Deployment
- **Commit**: `5681bfa` - Fix KeyError(0) in thread_manager: use dict keys for RealDictCursor
- **Status**: Deployed to Railway production
- **Environment**: `laudable-dedication/production/sentinel_ai_rss`

## Frontend Impact
Once deployed, the frontend should:
- Successfully load `/api/chat/threads/usage` data
- Display thread usage statistics
- No more 500 errors on page load
- Thread management UI fully functional

## Prevention
When using `RealDictCursor`:
1. Always use dict key access: `row['column_name']`
2. Never use index access: `row[0]`
3. For function calls, use aliases: `SELECT func() as result`
4. Check all `fetchone()[x]` patterns during code review

---

**Fixed**: November 22, 2025
**Railway Logs Confirmed**: Error eliminated after deployment
