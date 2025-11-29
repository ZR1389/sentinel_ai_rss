"""Chat thread management with dual-limit model.

Implements hybrid threading:
  - Active thread count limit (excludes archived)
  - Per-thread message cap
  - Monthly message quota (global safety valve)
  - Archive/unarchive (PRO+ only)
  - Soft delete with 30-day restore window
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor, Json
import os

try:
    from core.config import CONFIG
    DATABASE_URL = CONFIG.database.url
except Exception:
    DATABASE_URL = os.environ.get('DATABASE_PUBLIC_URL')

try:
    from config_data.plans import get_plan_feature, PLAN_FEATURES
except Exception:
    def get_plan_feature(plan: str, feature: str, default=None):
        return default
    PLAN_FEATURES = {}

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg2.connect(DATABASE_URL)

def get_thread_limits(plan: str) -> Dict[str, Any]:
    """Get thread limits for a given plan."""
    limits = {
        'threads_max': get_plan_feature(plan, 'conversation_threads'),
        'messages_per_thread': get_plan_feature(plan, 'messages_per_thread'),
        'messages_monthly': get_plan_feature(plan, 'chat_messages_monthly'),
        'can_archive': get_plan_feature(plan, 'can_archive_threads', False),
        'can_export_pdf': get_plan_feature(plan, 'can_export_pdf', False)
    }
    return limits

# ---------------- Thread Creation ----------------

def create_thread(user_id: int, plan: str, title: str, messages: List[Dict], investigation_topic: str = None) -> Dict[str, Any]:
    """Create new thread with validation."""
    # Check 1: Active thread count
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT COUNT(*) as active_count 
            FROM chat_threads 
            WHERE user_id=%s AND is_archived=FALSE AND is_deleted=FALSE
        """, (user_id,))
        active_count = cur.fetchone()['active_count']
    
    thread_limit = get_plan_feature(plan, 'conversation_threads')
    if thread_limit is not None and active_count >= thread_limit:
        can_archive = get_plan_feature(plan, 'can_archive_threads', False)
        raise ValueError(f"Max active threads ({thread_limit}) reached. " +
                        ("Archive old threads to continue." if can_archive else "Delete an old thread or upgrade to PRO."))
    
    # Check 2: Per-thread message limit (at creation)
    msg_limit = get_plan_feature(plan, 'messages_per_thread')
    if msg_limit is not None and len(messages) > msg_limit:
        raise ValueError(f"Exceeds per-thread message limit ({msg_limit})")
    
    # Check 3: Monthly quota
    monthly_limit = get_plan_feature(plan, 'chat_messages_monthly')
    if monthly_limit:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT get_monthly_message_count(%s)", (user_id,))
            monthly_used = cur.fetchone()[0]
            if monthly_used + len(messages) > monthly_limit:
                raise ValueError(f"Monthly message quota ({monthly_limit}) exceeded")
    
    # Create thread
    thread_uuid = str(uuid.uuid4())
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO chat_threads (user_id, thread_uuid, title, investigation_topic, message_count)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, thread_uuid, created_at
        """, (user_id, thread_uuid, title, investigation_topic, len(messages)))
        thread = cur.fetchone()
        thread_id = thread['id']
        
        # Insert messages
        for msg in messages:
            cur.execute("""
                INSERT INTO chat_messages (thread_id, role, content, timestamp)
                VALUES (%s, %s, %s, %s)
            """, (thread_id, msg['role'], msg['content'], msg.get('timestamp', datetime.utcnow())))
        
        conn.commit()
        return {
            'thread_id': thread['thread_uuid'],
            'created_at': thread['created_at'].isoformat() + 'Z'
        }

# ---------------- Thread Retrieval ----------------

def list_threads(user_id: int, plan: str, archived: str = 'false') -> Dict[str, Any]:
    """List user threads with usage stats."""
    # Build query based on archive filter
    if archived == 'true':
        where_clause = "is_archived=TRUE AND is_deleted=FALSE"
    elif archived == 'all':
        where_clause = "is_deleted=FALSE"
    else:  # 'false' (default)
        where_clause = "is_archived=FALSE AND is_deleted=FALSE"
    
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""
            SELECT thread_uuid, title, investigation_topic, message_count, 
                   is_archived, created_at, updated_at,
                   (SELECT content FROM chat_messages WHERE thread_id=chat_threads.id ORDER BY created_at DESC LIMIT 1) as last_message_preview
            FROM chat_threads
            WHERE user_id=%s AND {where_clause}
            ORDER BY updated_at DESC
        """, (user_id,))
        threads = cur.fetchall() or []
        
        # Get usage stats
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE is_archived=FALSE) as active_count,
                   COUNT(*) FILTER (WHERE is_archived=TRUE) as archived_count
            FROM chat_threads
            WHERE user_id=%s AND is_deleted=FALSE
        """, (user_id,))
        counts = cur.fetchone()
        
        cur.execute("SELECT get_monthly_message_count(%s)", (user_id,))
        monthly_used = cur.fetchone()[0]
    
    thread_limit = get_plan_feature(plan, 'conversation_threads')
    monthly_limit = get_plan_feature(plan, 'chat_messages_monthly')
    
    return {
        'threads': [dict(t) for t in threads],
        'total': len(threads),
        'usage': {
            'active_threads': counts['active_count'],
            'threads_limit': thread_limit,
            'archived_threads': counts['archived_count'],
            'monthly_messages_used': monthly_used,
            'monthly_messages_limit': monthly_limit,
            'can_archive': get_plan_feature(plan, 'can_archive_threads', False)
        }
    }

def get_thread(user_id: int, thread_uuid: str) -> Dict[str, Any] | None:
    """Get full thread with messages."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, thread_uuid, title, investigation_topic, is_archived, 
                   message_count, created_at, updated_at
            FROM chat_threads
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE
        """, (thread_uuid, user_id))
        thread = cur.fetchone()
        if not thread:
            return None
        
        cur.execute("""
            SELECT role, content, timestamp
            FROM chat_messages
            WHERE thread_id=%s
            ORDER BY created_at
        """, (thread['id'],))
        messages = cur.fetchall() or []
    
    return {
        'thread_id': thread['thread_uuid'],
        'title': thread['title'],
        'investigation_topic': thread['investigation_topic'],
        'is_archived': thread['is_archived'],
        'message_count': thread['message_count'],
        'messages': [dict(m) for m in messages],
        'created_at': thread['created_at'].isoformat() + 'Z',
        'updated_at': thread['updated_at'].isoformat() + 'Z'
    }

# ---------------- Thread Updates ----------------

def update_thread(user_id: int, plan: str, thread_uuid: str, title: str = None, investigation_topic: str = None, append_messages: List[Dict] = None) -> Dict[str, Any]:
    """Update thread metadata or append messages."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get thread
        cur.execute("SELECT id, message_count FROM chat_threads WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE", (thread_uuid, user_id))
        thread = cur.fetchone()
        if not thread:
            raise ValueError("Thread not found")
        thread_id = thread['id']
        current_count = thread['message_count']
        
        # Check per-thread message limit if appending
        if append_messages:
            msg_limit = get_plan_feature(plan, 'messages_per_thread')
            if msg_limit is not None and current_count + len(append_messages) > msg_limit:
                raise ValueError(f"Thread message limit ({msg_limit}) reached")
            
            # Check monthly quota
            monthly_limit = get_plan_feature(plan, 'chat_messages_monthly')
            if monthly_limit:
                cur.execute("SELECT get_monthly_message_count(%s)", (user_id,))
                monthly_used = cur.fetchone()[0]
                if monthly_used + len(append_messages) > monthly_limit:
                    raise ValueError(f"Monthly message quota ({monthly_limit}) exceeded")
            
            # Insert messages
            for msg in append_messages:
                cur.execute("""
                    INSERT INTO chat_messages (thread_id, role, content, timestamp)
                    VALUES (%s, %s, %s, %s)
                """, (thread_id, msg['role'], msg['content'], msg.get('timestamp', datetime.utcnow())))
        
        # Update metadata
        updates = []
        params = []
        if title is not None:
            updates.append("title=%s")
            params.append(title)
        if investigation_topic is not None:
            updates.append("investigation_topic=%s")
            params.append(investigation_topic)
        updates.append("updated_at=NOW()")
        
        if updates:
            params.append(thread_uuid)
            params.append(user_id)
            cur.execute(f"UPDATE chat_threads SET {', '.join(updates)} WHERE thread_uuid=%s AND user_id=%s RETURNING updated_at", params)
            updated_at = cur.fetchone()['updated_at']
        else:
            updated_at = datetime.utcnow()
        
        conn.commit()
        return {'updated_at': updated_at.isoformat() + 'Z'}

# ---------------- Archive Management ----------------

def archive_thread(user_id: int, plan: str, thread_uuid: str) -> Dict[str, Any]:
    """Archive thread (PRO+ only)."""
    if not get_plan_feature(plan, 'can_archive_threads', False):
        raise ValueError("Archiving requires PRO plan or higher")
    
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            UPDATE chat_threads 
            SET is_archived=TRUE, archived_at=NOW(), updated_at=NOW()
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE
            RETURNING archived_at
        """, (thread_uuid, user_id))
        result = cur.fetchone()
        if not result:
            raise ValueError("Thread not found")
        
        # Get remaining active count
        cur.execute("SELECT COUNT(*) as active FROM chat_threads WHERE user_id=%s AND is_archived=FALSE AND is_deleted=FALSE", (user_id,))
        active_count = cur.fetchone()['active']
        
        conn.commit()
        return {
            'archived_at': result['archived_at'].isoformat() + 'Z',
            'active_threads_remaining': active_count
        }

def unarchive_thread(user_id: int, plan: str, thread_uuid: str) -> Dict[str, Any]:
    """Restore thread from archive."""
    # Check active thread limit
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) as active FROM chat_threads WHERE user_id=%s AND is_archived=FALSE AND is_deleted=FALSE", (user_id,))
        active_count = cur.fetchone()['active']
    
    thread_limit = get_plan_feature(plan, 'conversation_threads')
    if thread_limit is not None and active_count >= thread_limit:
        raise ValueError(f"Max active threads ({thread_limit}). Archive another thread first.")
    
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE chat_threads 
            SET is_archived=FALSE, archived_at=NULL, updated_at=NOW()
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE AND is_archived=TRUE
        """, (thread_uuid, user_id))
        if cur.rowcount == 0:
            raise ValueError("Thread not found or not archived")
        conn.commit()
    
    return {'unarchived_at': datetime.utcnow().isoformat() + 'Z'}

# ---------------- Deletion ----------------

def delete_thread(user_id: int, thread_uuid: str) -> Dict[str, Any]:
    """Soft-delete thread."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE chat_threads 
            SET is_deleted=TRUE, updated_at=NOW()
            WHERE thread_uuid=%s AND user_id=%s AND is_deleted=FALSE
        """, (thread_uuid, user_id))
        if cur.rowcount == 0:
            raise ValueError("Thread not found")
        conn.commit()
    return {'message': 'Thread deleted'}

__all__ = [
    'create_thread', 'list_threads', 'get_thread', 'update_thread',
    'archive_thread', 'unarchive_thread', 'delete_thread'
]
