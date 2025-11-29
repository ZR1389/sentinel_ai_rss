import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from rq import get_current_job, Queue

# Reuse existing service logic and caching
from services.geocoding_service import geocode, _normalize_location, _get_redis, enqueue_geocode, get_quota_status

logger = logging.getLogger("geocode_worker")

# Backoff schedule in seconds for transient failures (approx)
BACKOFF_STEPS = [30, 120, 300, 600, 1200]


def _next_midnight_utc() -> datetime:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).date()
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc)


def _schedule_retry(location: str, reason: str, attempt: int = 0) -> None:
    """Schedule a retry via RQ with exponential backoff or next-day when quota is out."""
    r = _get_redis()
    if not r:
        logger.warning("[geocode_worker] Redis unavailable, cannot schedule retry")
        return
    q = Queue('geocoding', connection=r, default_timeout=120)

    # Quota-aware: if OpenCage exhausted, schedule at next midnight UTC
    quota = get_quota_status()
    if quota and quota.get('remaining', 0) <= 0:
        run_at = _next_midnight_utc() + timedelta(seconds=30)
        logger.info(f"[geocode_worker] Quota exhausted. Requeue '{location}' at {run_at.isoformat()}")
        q.enqueue_at(run_at, 'workers.geocode_worker.process_geocode', location=location, priority=0)
        return

    # Otherwise, exponential backoff with jitter
    step_idx = min(attempt, len(BACKOFF_STEPS) - 1)
    delay = BACKOFF_STEPS[step_idx]
    # small jitter +/-10%
    jitter = int(delay * 0.1)
    import random
    delay = delay + random.randint(-jitter, jitter)
    when = datetime.now(timezone.utc) + timedelta(seconds=delay)
    logger.info(f"[geocode_worker] Retry '{location}' in ~{delay}s due to {reason}")
    q.enqueue_at(when, 'workers.geocode_worker.process_geocode', location=location, priority=0)


def _clear_inflight_flag(location: str) -> None:
    try:
        r = _get_redis()
        if not r:
            return
        norm = _normalize_location(location)
        loc_hash = __import__('hashlib').md5(norm.encode()).hexdigest()[:12]
        r.srem('geocoding:inflight', loc_hash)
    except Exception:
        pass


def process_geocode(location: str, priority: int = 0) -> Optional[dict]:
    """RQ job: perform geocoding for a single location with quota-aware pacing.
    Returns result dict or None. On success, caches are updated by geocoding_service.
    """
    job = get_current_job()  # type: ignore
    attempt = 0
    try:
        attempt = int(getattr(job, 'meta', {}).get('attempt', 0)) if job else 0
    except Exception:
        attempt = 0

    try:
        # Force API so worker actually fills caches on misses
        result = geocode(location, force_api=True)
        if result:
            logger.info(f"[geocode_worker] Geocoded '{location}' -> ({result['lat']}, {result['lon']})")
            return result
        else:
            # Decide retry based on quota; otherwise transient backoff
            _schedule_retry(location, reason="no_result_or_quota", attempt=attempt)
            # track attempt count
            if job:
                job.meta['attempt'] = attempt + 1
                job.save_meta()
            return None
    except Exception as e:
        logger.warning(f"[geocode_worker] Error geocoding '{location}': {e}")
        _schedule_retry(location, reason="exception", attempt=attempt)
        if job:
            job.meta['attempt'] = attempt + 1
            job.save_meta()
        return None
    finally:
        # Clear inflight so future enqueue can happen if needed
        _clear_inflight_flag(location)
