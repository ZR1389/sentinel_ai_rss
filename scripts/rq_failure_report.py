#!/usr/bin/env python3
"""
List recent failed RQ jobs and their metadata.
Usage:
  REDIS_URL=redis://... python scripts/rq_failure_report.py [limit]
"""
import os
import sys
from datetime import datetime

try:
    import redis
    from rq import Queue
    from rq.registry import FailedJobRegistry
    from rq.job import Job
except Exception as e:
    print("Missing rq/redis packages:", e)
    sys.exit(1)

REDIS_URL = os.getenv('REDIS_URL') or os.getenv('ADMIN_LIMITER_REDIS_URL')
if not REDIS_URL:
    print("REDIS_URL not set")
    sys.exit(2)

conn = redis.from_url(REDIS_URL)
queue = Queue('fallback', connection=conn)
reg = FailedJobRegistry('fallback', connection=conn)
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50

job_ids = reg.get_job_ids()[:limit]
print(f"Failed jobs (showing up to {limit}): {len(job_ids)}")
for jid in job_ids:
    try:
        job = Job.fetch(jid, connection=conn)
        meta = job.meta or {}
        enq = job.enqueued_at.isoformat() if job.enqueued_at else None
        ended = job.ended_at.isoformat() if job.ended_at else None
        print("- job:", jid)
        print("  status:", job.get_status())
        print("  enqueued_at:", enq)
        print("  ended_at:", ended)
        print("  correlation_id:", meta.get('correlation_id'))
        print("  acting_email:", meta.get('acting_email'))
        print("  country/region:", meta.get('country'), '/', meta.get('region'))
        print("  attempts/max:", meta.get('attempts'), '/', meta.get('max_retries'))
        print("  exc:")
        print("    ", (job.exc_info or '').splitlines()[-1] if job.exc_info else '')
    except Exception as e:
        print("- job:", jid, "(failed to fetch)", e)
