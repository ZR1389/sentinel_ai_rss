"""Chat thread management with dual-limit model.

Implements comprehensive thread management:
  - Active thread count limit (excludes archived/deleted)
  - Per-thread message cap
  - Monthly message quota (global safety valve)
  - Archive/unarchive (PRO+ only)
  - Soft delete with 30-day restore window
  - Pagination support
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
import os

try:
    from config import CONFIG
    DATABASE_URL = CONFIG.database.url
except Exception:
    DATABASE_URL = os.environ.get('DATABASE_PUBLIC_URL')

try:
    # Updated import path after renaming plan configuration package to config_data
    from config_data.plans import get_plan_feature
except Exception:
    def get_plan_feature(plan: str, feature: str, default=None):
        return default

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg2.connect(DATABASE_URL)

def get_thread_limits(plan: str) -> Dict[str, Any]:
    """Get thread limits for a given plan."""
    return {
        'threads_max': get_plan_feature(plan, 'conversation_threads'),
        'messages_per_thread': get_plan_feature(plan, 'messages_per_thread'),
        'messages_monthly': get_plan_feature(plan, 'chat_messages_monthly'),
        'can_archive': get_plan_feature(plan, 'can_archive_threads', False),
        'can_export_pdf': get_plan_feature(plan, 'can_export_pdf', False)
    }

def get_usage_stats(user_id: int, plan: str) -> Dict[str, Any]:
    """Get comprehensive usage statistics."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Active and archived counts
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE is_archived=FALSE) as active_count,
                   COUNT(*) FILTER (WHERE is_archived=TRUE) as archived_count,
                   COUNT(*) FILTER (WHERE is_deleted=TRUE AND updated_at > NOW() - INTERVAL '30 days') as deleted_count
            FROM chat_threads
            WHERE user_id=%s AND (is_deleted=FALSE OR (is_deleted=TRUE AND updated_at > NOW() - INTERVAL '30 days'))
        """, (user_id,))
        counts = cur.fetchone()
        
        # Monthly message count
        cur.execute("SELECT get_monthly_message_count(%s) as count", (user_id,))
        monthly_used = cur.fetchone()['count']
    
    limits = get_thread_limits(plan)
    monthly_remaining = None
    if limits['messages_monthly']:
        monthly_remaining = max(0, limits['messages_monthly'] - monthly_used)
    
    return {
        'active_threads': counts['active_count'],
        'archived_threads': counts['archived_count'],
        'deleted_threads': counts['deleted_count'],
        'monthly_messages_used': monthly_used,
        'monthly_messages_remaining': monthly_remaining
    }

# ---------------- 1. Create Thread ----------------

def create_thread(user_id: int, plan: str, title: str, messages: List[Dict], 
                 investigation_topic: Optional[str] = None) -> Dict[str, Any]:
    """Create new thread with full validation.
    
    Raises:
        ValueError: With user-friendly error message if any limit exceeded
    """
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check 1: Active thread count
        cur.execute("""
            SELECT COUNT(*) as active_count 
            FROM chat_threads 
            WHERE user_id=%s AND is_archived=FALSE AND is_deleted=FALSE
        """, (user_id,))
        active_count = cur.fetchone()['active_count']
        
        limits = get_thread_limits(plan)
        thread_limit = limits['threads_max']
        
        if thread_limit is not None and active_count >= thread_limit:
            raise ValueError(f"Max active threads ({thread_limit}) reached")
        
        # Check 2: Per-thread message limit
        msg_limit = limits['messages_per_thread']
        if msg_limit is not None and len(messages) > msg_limit:
            raise ValueError(f"Message count exceeds per-thread limit ({msg_limit})")
        
        # Check 3: Monthly quota
        monthly_limit = limits['messages_monthly']
        if monthly_limit:
            cur.execute("SELECT get_monthly_message_count(%s) as count", (user_id,))
            monthly_used = cur.fetchone()['count']
            if monthly_used + len(messages) > monthly_limit:
                raise ValueError(f"Monthly message quota ({monthly_limit}) exceeded")
        
        # Create thread
        thread_uuid = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO chat_threads (user_id, thread_uuid, title, investigation_topic, message_count, thread_messages_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, thread_uuid, created_at, updated_at
        """, (user_id, thread_uuid, title, investigation_topic, len(messages), len(messages)))
        thread = cur.fetchone()
        thread_id = thread['id']
        
        # Insert messages
        for msg in messages:
            ts = msg.get('timestamp')
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            cur.execute("""
                INSERT INTO chat_messages (thread_id, role, content, timestamp)
                VALUES (%s, %s, %s, %s)
            """, (thread_id, msg['role'], msg['content'], ts or datetime.utcnow()))
        
        conn.commit()
        
        # Get usage stats
        usage = get_usage_stats(user_id, plan)
        
        return {
            'thread': {
                'id': thread_id,
                'uuid': thread['thread_uuid'],
                'title': title,
                'investigation_topic': investigation_topic,
                'message_count': len(messages),
                'created_at': thread['created_at'].isoformat() + 'Z',
                'updated_at': thread['updated_at'].isoformat() + 'Z',
                'is_archived': False
            },
            'usage': {
                **usage,
                'threads_limit': limits['threads_max'],
                'thread_messages': len(messages),
                'thread_message_limit': limits['messages_per_thread'],
                'monthly_messages_limit': limits['messages_monthly']
            }
        }

# ---------------- 2. List Threads ----------------

def list_threads(user_id: int, plan: str, archived: str = 'false', 
                page: int = 1, limit: int = 20) -> Dict[str, Any]:
    """List user threads with pagination and filtering."""
    # Validate pagination
    limit = min(limit, 50)  # Max 50 per page
    offset = (page - 1) * limit
    
    # Build filter
    if archived == 'true':
        where_clause = "is_archived=TRUE AND is_deleted=FALSE"
    elif archived == 'all':
        where_clause = "is_deleted=FALSE"
    else:  # 'false' (default)
        where_clause = "is_archived=FALSE AND is_deleted=FALSE"
    
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get total count
        cur.execute(f"""
            SELECT COUNT(*) as total
            FROM chat_threads
            WHERE user_id=%s AND {where_clause}
        """, (user_id,))
        total = cur.fetchone()['total']
        
        # Get threads
        cur.execute(f"""
            SELECT id, thread_uuid, title, investigation_topic, message_count, 
                   is_archived, created_at, updated_at
            FROM chat_threads
            WHERE user_id=%s AND {where_clause}
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s
        """, (user_id, limit, offset))
        threads = cur.fetchall() or []
    
    # Convert to dicts
    thread_list = []
    for t in threads:
        thread_list.append({
            'id': t['id'],
            'uuid': str(t['thread_uuid']),
            'title': t['title'],
            'investigation_topic': t['investigation_topic'],
            'message_count': t['message_count'],
            'created_at': t['created_at'].isoformat() + 'Z',
            'updated_at': t['updated_at'].isoformat() + 'Z',
            'is_archived': t['is_archived']
        })
    
    usage = get_usage_stats(user_id, plan)
    limits = get_thread_limits(plan)
    
    return {
        'threads': thread_list,
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'total_pages': (total + limit - 1) // limit
        },
        'usage': {
            **usage,
            **limits
        },
        'plan': plan
    }

# ---------------- 3. Get Thread ----------------

def get_thread(user_id: int, plan: str, thread_uuid: str) -> Dict[str, Any]:
    """Get full thread with all messages."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get thread
        cur.execute("""
            SELECT id, thread_uuid, title, investigation_topic, message_count,
                   is_archived, created_at, updated_at
            FROM chat_threads
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE
        """, (thread_uuid, user_id))
        thread = cur.fetchone()
        
        if not thread:
            return None
        
        thread_id = thread['id']
        
        # Get messages
        cur.execute("""
            SELECT id, role, content, timestamp
            FROM chat_messages
            WHERE thread_id=%s
            ORDER BY timestamp ASC
        """, (thread_id,))
        messages = cur.fetchall() or []
    
    limits = get_thread_limits(plan)
    usage = get_usage_stats(user_id, plan)
    
    return {
        'thread': {
            'id': thread['id'],
            'uuid': str(thread['thread_uuid']),
            'title': thread['title'],
            'investigation_topic': thread['investigation_topic'],
            'message_count': thread['message_count'],
            'created_at': thread['created_at'].isoformat() + 'Z',
            'updated_at': thread['updated_at'].isoformat() + 'Z',
            'is_archived': thread['is_archived'],
            'messages': [
                {
                    'id': m['id'],
                    'role': m['role'],
                    'content': m['content'],
                    'timestamp': m['timestamp'].isoformat() + 'Z'
                }
                for m in messages
            ]
        },
        'usage': {
            'thread_messages': thread['message_count'],
            'thread_message_limit': limits['messages_per_thread'],
            'monthly_messages_used': usage['monthly_messages_used'],
            'monthly_messages_limit': limits['messages_monthly']
        }
    }

# ---------------- 4. Add Messages to Thread ----------------

def add_messages(user_id: int, plan: str, thread_uuid: str, 
                messages: List[Dict]) -> Dict[str, Any]:
    """Append messages to existing thread with validation."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get thread
        cur.execute("""
            SELECT id, message_count, thread_messages_count, is_archived
            FROM chat_threads
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE
        """, (thread_uuid, user_id))
        thread = cur.fetchone()
        
        if not thread:
            raise ValueError("Thread not found")
        
        if thread['is_archived']:
            raise ValueError("Cannot add messages to archived thread")
        
        thread_id = thread['id']
        current_count = thread['thread_messages_count']  # Use denormalized counter for performance
        
        limits = get_thread_limits(plan)
        
        # Check per-thread limit
        msg_limit = limits['messages_per_thread']
        if msg_limit is not None and current_count + len(messages) > msg_limit:
            raise ValueError(f"Thread has reached its {msg_limit}-message limit")
        
        # Check monthly quota
        monthly_limit = limits['messages_monthly']
        if monthly_limit:
            cur.execute("SELECT get_monthly_message_count(%s) as count", (user_id,))
            monthly_used = cur.fetchone()['count']
            if monthly_used + len(messages) > monthly_limit:
                raise ValueError(f"Monthly message quota ({monthly_limit}) exceeded")
        
        # Insert messages
        for msg in messages:
            ts = msg.get('timestamp')
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            cur.execute("""
                INSERT INTO chat_messages (thread_id, role, content, timestamp)
                VALUES (%s, %s, %s, %s)
            """, (thread_id, msg['role'], msg['content'], ts or datetime.utcnow()))
        
        # Update thread
        cur.execute("""
            UPDATE chat_threads
            SET message_count = message_count + %s, 
                thread_messages_count = thread_messages_count + %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING thread_messages_count
        """, (len(messages), len(messages), thread_id))
        new_count = cur.fetchone()['thread_messages_count']
        
        conn.commit()
        
        usage = get_usage_stats(user_id, plan)
        
        return {
            'messages_added': len(messages),
            'usage': {
                'thread_messages': new_count,
                'thread_message_limit': limits['messages_per_thread'],
                'monthly_messages_used': usage['monthly_messages_used'],
                'monthly_messages_limit': limits['messages_monthly']
            }
        }

# ---------------- 5. Update Thread Title ----------------

def update_title(user_id: int, thread_uuid: str, title: str) -> Dict[str, Any]:
    """Update thread title."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            UPDATE chat_threads
            SET title=%s, updated_at=NOW()
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE
            RETURNING thread_uuid, title, updated_at
        """, (title, thread_uuid, user_id))
        thread = cur.fetchone()
        
        if not thread:
            return None
        
        conn.commit()
        
        return {
            'uuid': str(thread['thread_uuid']),
            'title': thread['title'],
            'updated_at': thread['updated_at'].isoformat() + 'Z'
        }

# ---------------- 6. Archive Thread ----------------

def archive_thread(user_id: int, plan: str, thread_uuid: str) -> Dict[str, Any]:
    """Archive thread (PRO+ only)."""
    limits = get_thread_limits(plan)
    if not limits['can_archive']:
        raise ValueError("Thread archiving requires PRO plan or higher")
    
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            UPDATE chat_threads
            SET is_archived=TRUE, archived_at=NOW(), updated_at=NOW()
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE AND is_archived=FALSE
            RETURNING archived_at
        """, (thread_uuid, user_id))
        result = cur.fetchone()
        
        if not result:
            return None
        
        conn.commit()
        
        usage = get_usage_stats(user_id, plan)
        
        return {
            'archived_at': result['archived_at'].isoformat() + 'Z',
            'usage': {
                'active_threads': usage['active_threads'],
                'threads_limit': limits['threads_max'],
                'archived_threads': usage['archived_threads']
            }
        }

# ---------------- 7. Unarchive Thread ----------------

def unarchive_thread(user_id: int, plan: str, thread_uuid: str) -> Dict[str, Any]:
    """Restore thread from archive."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check active limit
        cur.execute("""
            SELECT COUNT(*) as active_count 
            FROM chat_threads 
            WHERE user_id=%s AND is_archived=FALSE AND is_deleted=FALSE
        """, (user_id,))
        active_count = cur.fetchone()['active_count']
        
        limits = get_thread_limits(plan)
        thread_limit = limits['threads_max']
        
        if thread_limit is not None and active_count >= thread_limit:
            raise ValueError(f"Max active threads ({thread_limit}) reached. Archive another thread first.")
        
        # Unarchive
        cur.execute("""
            UPDATE chat_threads
            SET is_archived=FALSE, archived_at=NULL, updated_at=NOW()
            WHERE thread_uuid=%s AND user_id=%s AND is_archived=TRUE
            RETURNING updated_at
        """, (thread_uuid, user_id))
        result = cur.fetchone()
        
        if not result:
            return None
        
        conn.commit()
        
        usage = get_usage_stats(user_id, plan)
        
        return {
            'unarchived_at': result['updated_at'].isoformat() + 'Z',
            'usage': {
                'active_threads': usage['active_threads'],
                'threads_limit': limits['threads_max'],
                'archived_threads': usage['archived_threads']
            }
        }

# ---------------- 8. Delete Thread (Soft) ----------------

def delete_thread(user_id: int, plan: str, thread_uuid: str) -> Dict[str, Any]:
    """Soft delete thread (30-day restore window)."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            UPDATE chat_threads
            SET is_deleted=TRUE, updated_at=NOW()
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE
            RETURNING updated_at
        """, (thread_uuid, user_id))
        result = cur.fetchone()
        
        if not result:
            return None
        
        conn.commit()
        
        deleted_at = result['updated_at']
        restore_until = deleted_at + timedelta(days=30)
        
        usage = get_usage_stats(user_id, plan)
        limits = get_thread_limits(plan)
        
        return {
            'deleted_at': deleted_at.isoformat() + 'Z',
            'restore_until': restore_until.isoformat() + 'Z',
            'usage': {
                'active_threads': usage['active_threads'],
                'threads_limit': limits['threads_max']
            }
        }

# ---------------- 9. Restore Deleted Thread ----------------

def restore_thread(user_id: int, plan: str, thread_uuid: str) -> Dict[str, Any]:
    """Restore soft-deleted thread (within 30 days)."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check if thread exists and within restore window
        cur.execute("""
            SELECT updated_at
            FROM chat_threads
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=TRUE
        """, (thread_uuid, user_id))
        result = cur.fetchone()
        
        if not result:
            return None
        
        deleted_at = result['updated_at']
        if datetime.utcnow() - deleted_at.replace(tzinfo=None) > timedelta(days=30):
            raise ValueError("Thread permanently deleted after 30-day grace period")
        
        # Check active limit
        cur.execute("""
            SELECT COUNT(*) as active_count 
            FROM chat_threads 
            WHERE user_id=%s AND is_archived=FALSE AND is_deleted=FALSE
        """, (user_id,))
        active_count = cur.fetchone()['active_count']
        
        limits = get_thread_limits(plan)
        thread_limit = limits['threads_max']
        
        if thread_limit is not None and active_count >= thread_limit:
            raise ValueError(f"Max active threads ({thread_limit}) reached. Delete another thread first.")
        
        # Restore
        cur.execute("""
            UPDATE chat_threads
            SET is_deleted=FALSE, updated_at=NOW()
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=TRUE
            RETURNING updated_at
        """, (thread_uuid, user_id))
        result = cur.fetchone()
        
        conn.commit()
        
        usage = get_usage_stats(user_id, plan)
        
        return {
            'restored_at': result['updated_at'].isoformat() + 'Z',
            'usage': {
                'active_threads': usage['active_threads'],
                'threads_limit': limits['threads_max']
            }
        }

# ---------------- 10. Get Usage Stats ----------------

def get_usage_overview(user_id: int, plan: str) -> Dict[str, Any]:
    """Get comprehensive usage statistics for UI display."""
    limits = get_thread_limits(plan)
    usage = get_usage_stats(user_id, plan)
    
    # Calculate current month range
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Calculate next month
    if now.month == 12:
        month_end = now.replace(year=now.year + 1, month=1, day=1) - timedelta(seconds=1)
    else:
        month_end = now.replace(month=now.month + 1, day=1) - timedelta(seconds=1)
    
    reset_in_days = (month_end - now).days
    
    return {
        'plan': plan,
        'limits': limits,
        'usage': usage,
        'current_month': {
            'start': month_start.isoformat() + 'Z',
            'end': month_end.isoformat() + 'Z',
            'reset_in_days': reset_in_days
        }
    }
