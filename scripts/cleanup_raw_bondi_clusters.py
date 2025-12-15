#!/usr/bin/env python3
"""
One-time cleanup for raw_alerts Bondi clusters.
- Cluster recent (7d) Bondi-related raw alerts
- Use cosine similarity on embeddings (0.88) with 48h window
- Prefer earlier + trusted sources; delete the rest
"""

import sys
import os
from datetime import datetime, timedelta
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import fetch_all, execute

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SIM_THRESHOLD = 0.6
WINDOW_HOURS = 48
PREFERRED = ['reuters.com', 'apnews.com', 'bbc.co.uk', 'nytimes.com', 'theguardian.com', 'abc.net.au']


def cosine_sim_from_title(t1: str, t2: str) -> float:
    """Fallback similarity using title word overlap when embeddings are not stored in raw_alerts."""
    words1 = set(w for w in (t1 or "").lower().split() if len(w) > 3)
    words2 = set(w for w in (t2 or "").lower().split() if len(w) > 3)
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / len(words1 | words2)


def load_raw_bondi(days=7):
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = """
    SELECT uuid, published, title, summary, source, country, city
    FROM raw_alerts
    WHERE (LOWER(title) LIKE %s OR LOWER(summary) LIKE %s)
      AND published >= %s
    ORDER BY published ASC
    """
    return fetch_all(q, ('%bondi%', '%bondi%', cutoff))


def cluster_alerts(rows):
    """Cluster alerts by title similarity within a time window."""
    clusters = []
    used = set()
    for i, r in enumerate(rows):
        if i in used:
            continue
        base_pub = r.get('published')
        cluster = [r]
        used.add(i)
        for j in range(i + 1, len(rows)):
            if j in used:
                continue
            other = rows[j]

            # Enforce 48h window
            dt1, dt2 = base_pub, other.get('published')
            try:
                if dt1 and dt2 and abs((dt2 - dt1).total_seconds()) > WINDOW_HOURS * 3600:
                    continue
            except Exception:
                pass

            # Title similarity
            sim = cosine_sim_from_title(r.get('title'), other.get('title'))
            if sim >= SIM_THRESHOLD:
                cluster.append(other)
                used.add(j)

        if len(cluster) > 1:
            clusters.append(cluster)
    return clusters


def pick_best(cluster):
    best = None
    best_score = -1
    for a in cluster:
        score = 10000
        pub = a.get('published')
        try:
            if pub:
                score -= pub.timestamp() / 1000
        except Exception:
            pass
        src = a.get('source') or ''
        if any(p in src for p in PREFERRED):
            score += 5000
        summary_len = len(a.get('summary') or '')
        score += min(summary_len/10, 500)
        if score > best_score:
            best_score = score
            best = a
    return best


def cleanup():
    rows = load_raw_bondi()
    if not rows:
        logger.info("No raw Bondi alerts found")
        return
    logger.info(f"Loaded {len(rows)} raw Bondi alerts")
    clusters = cluster_alerts(rows)
    logger.info(f"Found {len(clusters)} clusters with similarity >= {SIM_THRESHOLD}")
    total_removed = 0
    for idx, c in enumerate(clusters, 1):
        best = pick_best(c)
        if not best:
            continue
        to_delete = [a['uuid'] for a in c if a['uuid'] != best['uuid']]
        if to_delete:
            logger.info(f"Cluster {idx}: keep '{best.get('title','')[:70]}' ({best.get('source','')}); remove {len(to_delete)}")
            execute("DELETE FROM raw_alerts WHERE uuid = ANY(%s)", (to_delete,))
            total_removed += len(to_delete)
    logger.info(f"✅ Raw cleanup complete: removed {total_removed} duplicate/raw-near duplicates")


if __name__ == "__main__":
    try:
        cleanup()
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        sys.exit(1)
