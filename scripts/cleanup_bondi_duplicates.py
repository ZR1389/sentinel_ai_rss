#!/usr/bin/env python3
"""
One-time cleanup script to remove Bondi Beach duplicate alerts.
Keeps the earliest/best source for each semantically similar cluster.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import fetch_all, execute
from utils.risk_shared import get_embedding, embedding_manager
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def cleanup_bondi_duplicates():
    """Remove duplicate Bondi Beach alerts, keeping best representative from each cluster."""
    
    # Find all Bondi-related alerts from the last 7 days
    cutoff = datetime.utcnow() - timedelta(days=7)
    
    query = """
    SELECT uuid, published, title, summary, source, embedding
    FROM alerts
    WHERE (LOWER(title) LIKE %s OR LOWER(summary) LIKE %s)
      AND published >= %s
    ORDER BY published ASC
    """
    
    bondi_alerts = fetch_all(query, ('%bondi%', '%bondi%', cutoff))
    
    if not bondi_alerts:
        logger.info("No Bondi Beach alerts found to clean up")
        return
    
    logger.info(f"Found {len(bondi_alerts)} Bondi Beach alerts to deduplicate")
    
    # Group into clusters by semantic similarity
    clusters = []
    processed = set()
    
    for i, alert in enumerate(bondi_alerts):
        if i in processed:
            continue
            
        # Convert dict to regular dict if needed
        if not isinstance(alert, dict):
            alert = dict(alert)
            
        # Start new cluster with this alert
        cluster = [alert]
        processed.add(i)
        
        # Find similar alerts
        for j, other_alert in enumerate(bondi_alerts):
            if j in processed or j <= i:
                continue
            
            if not isinstance(other_alert, dict):
                other_alert = dict(other_alert)
            
            # Calculate similarity if embeddings available
            emb1 = alert.get('embedding')
            emb2 = other_alert.get('embedding')
            
            if emb1 and emb2:
                try:
                    # Cosine similarity
                    dot_product = sum(a * b for a, b in zip(emb1, emb2))
                    mag1 = (sum(a * a for a in emb1) ** 0.5)
                    mag2 = (sum(b * b for b in emb2) ** 0.5)
                    similarity = dot_product / (mag1 * mag2) if mag1 > 0 and mag2 > 0 else 0
                    
                    # Use aggressive threshold for breaking news
                    if similarity > 0.88:
                        cluster.append(other_alert)
                        processed.add(j)
                        continue
                except Exception as e:
                    logger.debug(f"Similarity calculation failed: {e}")
            
            # Fallback: simple title similarity
            title1 = alert.get('title', '').lower()
            title2 = other_alert.get('title', '').lower()
            
            # Count common significant words
            words1 = set(w for w in title1.split() if len(w) > 3)
            words2 = set(w for w in title2.split() if len(w) > 3)
            
            if words1 and words2:
                overlap = len(words1 & words2) / len(words1 | words2)
                if overlap > 0.6:
                    cluster.append(other_alert)
                    processed.add(j)
        
        if len(cluster) > 1:
            clusters.append(cluster)
    
    # Process each cluster
    total_removed = 0
    for idx, cluster in enumerate(clusters):
        logger.info(f"Cluster {idx+1}: {len(cluster)} similar alerts")
        
        # Choose best alert to keep
        # Priority: earliest published, then preferred sources
        preferred_sources = ['nytimes.com', 'theguardian.com', 'bbc.co.uk', 'reuters.com', 'apnews.com']
        
        best_alert = None
        best_score = -1
        
        for alert in cluster:
            if not isinstance(alert, dict):
                alert = dict(alert)
                
            score = 10000  # Base score to ensure it's always positive
            
            # Prefer earlier publication (most important factor)
            pub_date = alert.get('published')
            if pub_date:
                try:
                    if isinstance(pub_date, datetime):
                        # Earlier is better - use negative timestamp so earlier = higher score
                        score -= pub_date.timestamp() / 1000  # Scale down to reasonable range
                    elif isinstance(pub_date, str):
                        dt = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                        score -= dt.timestamp() / 1000
                except Exception as e:
                    logger.debug(f"Date scoring failed: {e}")
            
            # Prefer known sources
            source = alert.get('source', '')
            if any(pref in source for pref in preferred_sources):
                score += 5000
            
            # Prefer longer summaries (more informative)
            summary_len = len(alert.get('summary', '') or '')
            score += min(summary_len / 10, 500)  # Max 500 bonus
            
            logger.debug(f"    Score {score}: {alert.get('title', '')[:60]} ({source})")
            
            if best_alert is None or score > best_score:
                best_score = score
                best_alert = alert
        
        # Delete all except best
        if not best_alert:
            logger.warning(f"  No best alert found for cluster {idx+1}, skipping")
            continue
            
        to_delete = [a['uuid'] for a in cluster if a['uuid'] != best_alert['uuid']]
        
        if to_delete:
            logger.info(f"  Keeping: {best_alert['title'][:80]} ({best_alert['source']})")
            logger.info(f"  Removing {len(to_delete)} duplicates")
            
            delete_query = "DELETE FROM alerts WHERE uuid = ANY(%s)"
            execute(delete_query, (to_delete,))
            total_removed += len(to_delete)
    
    logger.info(f"✅ Cleanup complete: removed {total_removed} duplicate alerts, kept {len(clusters)} unique events")

if __name__ == "__main__":
    try:
        cleanup_bondi_duplicates()
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        sys.exit(1)
