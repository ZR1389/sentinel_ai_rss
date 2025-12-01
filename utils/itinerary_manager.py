"""
utils/itinerary_manager.py - Travel Risk Itinerary Persistence

Manages CRUD operations for user travel itineraries with route risk analysis.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from psycopg2.extras import RealDictCursor, Json
import logging

logger = logging.getLogger(__name__)

def _conn():
    """Get database connection using db_utils pool."""
    try:
        from utils.db_utils import get_connection_pool
        pool = get_connection_pool()
        return pool.getconn()
    except Exception as e:
        logger.error(f"Failed to get DB connection: {e}")
        raise


def _return_conn(conn):
    """Return connection to pool."""
    try:
        from utils.db_utils import get_connection_pool
        pool = get_connection_pool()
        pool.putconn(conn)
    except Exception as e:
        logger.error(f"Failed to return DB connection: {e}")


def create_itinerary(
    user_id: int,
    data: Dict[str, Any],
    title: Optional[str] = None,
    description: Optional[str] = None,
    alerts_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a new travel itinerary.
    
    Args:
        user_id: User ID from authenticated session
        data: JSONB data containing waypoints, routes, risk_analysis, metadata
        title: Optional itinerary title
        description: Optional description
        
    Returns:
        Dict with created itinerary details
        
    Raises:
        ValueError: If data validation fails
    """
    # Validate required fields in data
    if not isinstance(data, dict):
        raise ValueError("Data must be a dictionary")
    
    if 'waypoints' not in data:
        raise ValueError("Data must contain 'waypoints' field")
    
    # Inject alerts_config (already validated/sanitized by caller) into data JSONB
    if alerts_config is not None:
        try:
            data["alerts_config"] = alerts_config
        except Exception:
            pass

    # Calculate destinations count from waypoints for denormalized column
    destinations_count = 0
    if 'waypoints' in data and isinstance(data['waypoints'], list):
        destinations_count = len(data['waypoints'])

    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO travel_itineraries 
                (user_id, title, description, data, destinations_count)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING 
                    id, itinerary_uuid, user_id, title, description, 
                    data, created_at, updated_at, version,
                    last_alert_sent_at, alerts_sent_count, destinations_count
            """, (user_id, title, description, Json(data), destinations_count))
            
            result = cur.fetchone()
            conn.commit()
            
            return dict(result)
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create itinerary: {e}")
        raise
    finally:
        _return_conn(conn)


def list_itineraries(
    user_id: int,
    limit: int = 20,
    offset: int = 0,
    include_deleted: bool = False
) -> List[Dict[str, Any]]:
    """
    List user's itineraries, ordered by created_at DESC.
    
    Args:
        user_id: User ID from authenticated session
        limit: Maximum number of results (default 20, max 100)
        offset: Offset for pagination
        include_deleted: Whether to include soft-deleted itineraries
        
    Returns:
        List of itinerary dicts
    """
    # Sanitize limits
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where_clause = "WHERE user_id = %s"
            if not include_deleted:
                where_clause += " AND is_deleted = FALSE"
            
            cur.execute(f"""
                SELECT 
                    id, itinerary_uuid, user_id, title, description,
                    data, created_at, updated_at, version,
                    is_deleted, deleted_at
                FROM travel_itineraries
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (user_id, limit, offset))
            
            results = cur.fetchall()
            return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"Failed to list itineraries: {e}")
        raise
    finally:
        _return_conn(conn)


def get_itinerary(
    user_id: int,
    itinerary_uuid: str,
    include_deleted: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Get a specific itinerary by UUID.
    
    Args:
        user_id: User ID (for authorization)
        itinerary_uuid: UUID of the itinerary
        include_deleted: Whether to return soft-deleted itineraries
        
    Returns:
        Itinerary dict or None if not found
    """
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where_clause = "WHERE user_id = %s AND itinerary_uuid = %s"
            if not include_deleted:
                where_clause += " AND is_deleted = FALSE"
            
            cur.execute(f"""
                SELECT 
                    id, itinerary_uuid, user_id, title, description,
                    data, created_at, updated_at, version,
                    is_deleted, deleted_at
                FROM travel_itineraries
                {where_clause}
            """, (user_id, itinerary_uuid))
            
            result = cur.fetchone()
            return dict(result) if result else None
    except Exception as e:
        logger.error(f"Failed to get itinerary: {e}")
        raise
    finally:
        _return_conn(conn)


def update_itinerary(
    user_id: int,
    itinerary_uuid: str,
    data: Optional[Dict[str, Any]] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    expected_version: Optional[int] = None,
    alerts_config: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    Update an existing itinerary with optimistic locking.
    
    Args:
        user_id: User ID (for authorization)
        itinerary_uuid: UUID of the itinerary
        data: Optional new JSONB data
        title: Optional new title
        description: Optional new description
        expected_version: Optional version for conflict detection (optimistic locking)
        
    Returns:
        Updated itinerary dict or None if not found
        
    Raises:
        ValueError: If expected_version provided and doesn't match current version (409 conflict)
    """
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check version if provided (optimistic locking)
            if expected_version is not None:
                cur.execute("""
                    SELECT version FROM travel_itineraries
                    WHERE user_id = %s AND itinerary_uuid = %s AND is_deleted = FALSE
                """, (user_id, itinerary_uuid))
                row = cur.fetchone()
                if not row:
                    return None
                if row['version'] != expected_version:
                    raise ValueError(f"Version conflict: expected {expected_version}, current is {row['version']}")
            
            # Build dynamic UPDATE query
            updates = []
            params = []
            
            if data is not None:
                # Calculate new destinations_count when data changes
                destinations_count = 0
                if 'waypoints' in data and isinstance(data['waypoints'], list):
                    destinations_count = len(data['waypoints'])
                
                updates.append("data = %s")
                params.append(Json(data))
                updates.append("destinations_count = %s")
                params.append(destinations_count)
            if title is not None:
                updates.append("title = %s")
                params.append(title)
            if description is not None:
                updates.append("description = %s")
                params.append(description)

            # If alerts_config provided without new data blob, fetch current data and merge
            if alerts_config is not None and data is None:
                cur.execute("""
                    SELECT data FROM travel_itineraries
                    WHERE user_id = %s AND itinerary_uuid = %s AND is_deleted = FALSE
                """, (user_id, itinerary_uuid))
                row_cur = cur.fetchone()
                if row_cur:
                    try:
                        existing_data = row_cur[0] if not isinstance(row_cur, dict) else row_cur['data']
                        if isinstance(existing_data, dict):
                            existing_data['alerts_config'] = alerts_config
                            # Recalculate destinations_count from merged data
                            destinations_count = 0
                            if 'waypoints' in existing_data and isinstance(existing_data['waypoints'], list):
                                destinations_count = len(existing_data['waypoints'])
                            
                            updates.append("data = %s")
                            params.append(Json(existing_data))
                            updates.append("destinations_count = %s")
                            params.append(destinations_count)
                    except Exception:
                        pass
            elif alerts_config is not None and data is not None:
                # data already provided; merge alerts_config directly
                try:
                    data['alerts_config'] = alerts_config
                    # Recalculate destinations_count from merged data
                    destinations_count = 0
                    if 'waypoints' in data and isinstance(data['waypoints'], list):
                        destinations_count = len(data['waypoints'])
                    # Need to replace last Json(data) param we previously appended
                    # Find both data and destinations_count params and update
                    for i in range(len(params)-1, -1, -1):
                        if isinstance(params[i], Json):
                            params[i] = Json(data)
                            # Update destinations_count param (should be next after Json)
                            if i+1 < len(params):
                                params[i+1] = destinations_count
                            break
                except Exception:
                    pass
            
            if not updates:
                # Nothing to update, just fetch current
                return get_itinerary(user_id, itinerary_uuid)
            
            # Increment version
            updates.append("version = version + 1")
            
            params.extend([user_id, itinerary_uuid])
            
            cur.execute(f"""
                UPDATE travel_itineraries
                SET {', '.join(updates)}
                WHERE user_id = %s AND itinerary_uuid = %s AND is_deleted = FALSE
                RETURNING 
                    id, itinerary_uuid, user_id, title, description,
                    data, created_at, updated_at, version,
                    last_alert_sent_at, alerts_sent_count, destinations_count
            """, params)
            
            result = cur.fetchone()
            conn.commit()
            
            return dict(result) if result else None
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to update itinerary: {e}")
        raise
    finally:
        _return_conn(conn)


def delete_itinerary(
    user_id: int,
    itinerary_uuid: str,
    soft: bool = True
) -> bool:
    """
    Delete an itinerary (soft delete by default).
    
    Args:
        user_id: User ID (for authorization)
        itinerary_uuid: UUID of the itinerary
        soft: If True, soft delete; if False, permanent delete
        
    Returns:
        True if deleted, False if not found
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            if soft:
                cur.execute("""
                    UPDATE travel_itineraries
                    SET is_deleted = TRUE, deleted_at = NOW()
                    WHERE user_id = %s AND itinerary_uuid = %s AND is_deleted = FALSE
                """, (user_id, itinerary_uuid))
            else:
                cur.execute("""
                    DELETE FROM travel_itineraries
                    WHERE user_id = %s AND itinerary_uuid = %s
                """, (user_id, itinerary_uuid))
            
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to delete itinerary: {e}")
        raise
    finally:
        _return_conn(conn)


def get_itinerary_stats(user_id: int) -> Dict[str, int]:
    """
    Get statistics about user's itineraries.
    
    Args:
        user_id: User ID
        
    Returns:
        Dict with counts: {count, active, deleted} (count = total)
    """
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    COUNT(*) as count,
                    COUNT(*) FILTER (WHERE is_deleted = FALSE) as active,
                    COUNT(*) FILTER (WHERE is_deleted = TRUE) as deleted
                FROM travel_itineraries
                WHERE user_id = %s
            """, (user_id,))
            
            result = cur.fetchone()
            return dict(result) if result else {'count': 0, 'active': 0, 'deleted': 0}
    except Exception as e:
        logger.error(f"Failed to get itinerary stats: {e}")
        raise
    finally:
        _return_conn(conn)
