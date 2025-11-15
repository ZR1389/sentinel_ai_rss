"""fallback_jobs.py — Asynchronous job queue for real-time fallback execution.

Provides a lightweight in-process job queue (thread + Queue) for executing
`perform_realtime_fallback` calls asynchronously. Optionally can be disabled
via env flag. Redis persistence for job status can be added later; current
implementation keeps everything in-memory (safe when running a single process).

Environment Variables:
  ENABLE_FALLBACK_JOB_QUEUE=true|false  (default: true) — master enable switch
  FALLBACK_JOB_POLL_INTERVAL_SEC=<float> (default: 0.25) — worker sleep interval

Public API:
  job_queue_enabled() -> bool
  submit_fallback_job(country, region, acting_email, acting_plan) -> dict
  get_fallback_job_status(job_id) -> dict | None
  list_fallback_jobs(limit=100) -> List[dict]

Job Status Lifecyle:
  queued -> running -> completed | error
"""

from __future__ import annotations

import os
import uuid
import time
import threading
import queue
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

try:
    from real_time_fallback import perform_realtime_fallback
except Exception as e:  # pragma: no cover
    logger.error("fallback_jobs: perform_realtime_fallback import failed: %s", e)
    def perform_realtime_fallback(country: Optional[str] = None, region: Optional[str] = None):  # type: ignore
        return []

# ---------------- Configuration ----------------

def _truthy(val: Optional[str]) -> bool:
    return str(val or "").lower() in {"1", "true", "yes", "on"}

_ENABLE = _truthy(os.getenv("ENABLE_FALLBACK_JOB_QUEUE", "true"))
_POLL_INTERVAL = float(os.getenv("FALLBACK_JOB_POLL_INTERVAL_SEC", "0.25"))
_ENABLE_REDIS_STORE = _truthy(os.getenv("ENABLE_REDIS_JOB_STORE", "true"))
_REDIS_URL = os.getenv("ADMIN_LIMITER_REDIS_URL") or os.getenv("REDIS_URL")
_USE_RQ_QUEUE = _truthy(os.getenv("USE_RQ_QUEUE", "false"))

# ---------------- Internal State ----------------

_jobs_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}
_job_queue: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_redis = None
_rq_queue = None

if _ENABLE_REDIS_STORE and _REDIS_URL:
    try:
        import redis  # type: ignore
        _redis = redis.from_url(_REDIS_URL)
        # Simple connectivity check (non-fatal)
        try:
            _redis.ping()
        except Exception:
            pass
        logger.info("[fallback_jobs] Redis job store enabled")
    except Exception as e:  # pragma: no cover
        logger.warning("[fallback_jobs] Redis init failed, using memory store only: %s", e)
        _redis = None

if _USE_RQ_QUEUE and _REDIS_URL:
    try:
        from rq import Queue  # type: ignore
        import redis  # type: ignore
        _rq_conn = redis.from_url(_REDIS_URL)
        _rq_queue = Queue("fallback", connection=_rq_conn)
        logger.info("[fallback_jobs] RQ queue enabled on Redis URL")
    except Exception as e:  # pragma: no cover
        logger.warning("[fallback_jobs] RQ init failed, falling back to in-memory queue: %s", e)
        _rq_queue = None


def job_queue_enabled() -> bool:
    return _ENABLE


def _start_worker_if_needed():
    global _worker_started
    if not job_queue_enabled():
        return
    if _worker_started:
        return

    def _worker_loop():
        logger.info("[fallback_jobs] Worker started (poll_interval=%s)", _POLL_INTERVAL)
        while True:
            try:
                job_id = _job_queue.get(timeout=5)
            except queue.Empty:
                continue
            with _jobs_lock:
                job = _jobs.get(job_id)
                if not job:
                    continue
                job["status"] = "running"
                job["started_at"] = time.time()
            try:
                attempts = perform_realtime_fallback(country=job.get("country"), region=job.get("region"))
                with _jobs_lock:
                    job["attempts"] = attempts
                    job["status"] = "completed"
                    job["finished_at"] = time.time()
                    job["elapsed_ms"] = int((job["finished_at"] - job["created_at"]) * 1000)
                    _persist_job(job)
            except Exception as e:  # pragma: no cover
                logger.error("[fallback_jobs] Job %s error: %s", job_id, e)
                with _jobs_lock:
                    job["status"] = "error"
                    job["error"] = str(e)
                    job["finished_at"] = time.time()
                    job["elapsed_ms"] = int((job["finished_at"] - job["created_at"]) * 1000)
                    _persist_job(job)
            finally:
                _job_queue.task_done()
            time.sleep(_POLL_INTERVAL)

    t = threading.Thread(target=_worker_loop, name="fallback-jobs-worker", daemon=True)
    t.start()
    _worker_started = True


def submit_fallback_job(
    country: str,
    region: Optional[str],
    acting_email: str,
    acting_plan: str,
) -> Dict[str, Any]:
    """Create and queue a fallback job. If queue disabled executes immediately."""
    job_id = str(uuid.uuid4())
    corr_id = str(uuid.uuid4())
    now = time.time()
    record: Dict[str, Any] = {
        "job_id": job_id,
        "correlation_id": corr_id,
        "country": country,
        "region": region,
        "acting_email": acting_email,
        "acting_plan": acting_plan,
        "status": "queued" if job_queue_enabled() else "running",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "attempts": [],
        "error": None,
        "elapsed_ms": None,
    }
    with _jobs_lock:
        _jobs[job_id] = record
        _persist_job(record)

    # RQ mode: enqueue and return immediately
    if _rq_queue is not None:
        try:
            from fallback_tasks import run_fallback_task
            # Configure retry/backoff via env
            try:
                from rq import Retry  # type: ignore
            except Exception:
                from rq.job import Retry  # type: ignore
            import os
            max_retries = int(os.getenv('FALLBACK_RQ_RETRY_MAX', '3'))
            backoff_env = os.getenv('FALLBACK_RQ_RETRY_BACKOFF', '10,30,60')
            intervals = []
            try:
                intervals = [int(x.strip()) for x in backoff_env.split(',') if x.strip()]
            except Exception:
                intervals = [10, 30, 60]
            retry = Retry(max=max_retries, interval=intervals if intervals else [10,30,60])
            meta = {
                "correlation_id": record.get("correlation_id"),
                "acting_email": acting_email,
                "acting_plan": acting_plan,
                "country": country,
                "region": region,
                "max_retries": max_retries,
                "attempts": 0,
            }
            rq_job = _rq_queue.enqueue(run_fallback_task, country, region, job_id=job_id, retry=retry, meta=meta)
            # Track in index for listing
            _index_job(job_id, record.get("created_at") or time.time())
            return record
        except Exception as e:  # pragma: no cover
            logger.warning("[fallback_jobs] RQ enqueue failed, using local queue: %s", e)

    if not job_queue_enabled():
        # Execute synchronously
        record["started_at"] = time.time()
        try:
            attempts = perform_realtime_fallback(country=country, region=region)
            record["attempts"] = attempts
            record["status"] = "completed"
            record["finished_at"] = time.time()
            record["elapsed_ms"] = int((record["finished_at"] - record["created_at"]) * 1000)
        except Exception as e:  # pragma: no cover
            record["status"] = "error"
            record["error"] = str(e)
            record["finished_at"] = time.time()
            record["elapsed_ms"] = int((record["finished_at"] - record["created_at"]) * 1000)
        _persist_job(record)
        return record

    _start_worker_if_needed()
    _job_queue.put(job_id)
    return record


def get_fallback_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    # If using RQ, try to merge RQ job state
    if _rq_queue is not None:
        try:
            from rq.job import Job  # type: ignore
            job = Job.fetch(job_id, connection=_rq_queue.connection)
            meta = job.meta or {}
            state = job.get_status()
            result = job.result if job.is_finished else None
            # Start with persisted record (Redis or memory)
            base = _load_job_local(job_id) or {}
            base.setdefault("job_id", job_id)
            base["status"] = "completed" if job.is_finished else ("failed" if job.is_failed else ("running" if job.is_started else "queued"))
            if result and isinstance(result, dict):
                base.update({
                    "attempts": result.get("attempts", []),
                    "finished_at": result.get("finished_at"),
                    "started_at": result.get("started_at"),
                    "elapsed_ms": result.get("elapsed_ms"),
                })
            return base
        except Exception:
            pass
    # Prefer Redis if available to allow cross-process visibility
    if _redis:
        try:
            data = _redis.get(f"fallback_job:{job_id}")
            if data:
                import json
                return json.loads(data)
        except Exception:
            pass
    return _load_job_local(job_id)


def list_fallback_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    if _rq_queue is not None and _redis is not None:
        try:
            # Use our indexing ZSET for recent jobs
            import json
            ids = _redis.zrevrange("fallback_jobs", 0, max(0, limit - 1))
            out: List[Dict[str, Any]] = []
            for jid in ids:
                jid_s = jid.decode("utf-8")
                # For each, load status (will merge RQ if available)
                st = get_fallback_job_status(jid_s)
                if st:
                    out.append(st)
            return out
        except Exception:
            pass
    if _redis:
        try:
            import json
            ids = _redis.zrevrange("fallback_jobs", 0, max(0, limit - 1))
            out: List[Dict[str, Any]] = []
            for jid in ids:
                data = _redis.get(f"fallback_job:{jid.decode('utf-8')}")
                if data:
                    out.append(json.loads(data))
            return out
        except Exception:
            pass
    with _jobs_lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.get("created_at", 0), reverse=True)
        return [dict(j) for j in jobs[:limit]]


def _persist_job(job: Dict[str, Any]) -> None:
    if not _redis:
        return
    try:
        import json
        jid = job.get("job_id")
        if not jid:
            return
        key = f"fallback_job:{jid}"
        _redis.set(key, json.dumps(job), ex=7 * 24 * 3600)
        _redis.zadd("fallback_jobs", {jid: float(job.get("created_at") or time.time())})
        _redis.expire("fallback_jobs", 7 * 24 * 3600)
    except Exception:  # pragma: no cover
        pass


def _index_job(job_id: str, created_at: float) -> None:
    if not _redis:
        return
    try:
        _redis.zadd("fallback_jobs", {job_id: float(created_at or time.time())})
        _redis.expire("fallback_jobs", 7 * 24 * 3600)
    except Exception:
        pass


def _load_job_local(job_id: str) -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return dict(job)


if __name__ == "__main__":  # Manual dev test
    logging.basicConfig(level=logging.INFO)
    j = submit_fallback_job("Atlantis", None, "tester@example.com", "FREE")
    print("Submitted job:", j["job_id"])
    while True:
        st = get_fallback_job_status(j["job_id"])
        print(st)
        if st and st["status"] in {"completed", "error"}:
            break
        time.sleep(0.5)