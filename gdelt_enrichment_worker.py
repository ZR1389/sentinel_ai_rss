#!/usr/bin/env python3
"""
GDELT Enrichment Worker
Processes unprocessed gdelt_events into raw_alerts table
(Threat Engine then enriches raw_alerts → alerts with unified scoring/SOCMINT)
"""
import os
import sys
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger("gdelt_enrichment")

DATABASE_URL = os.getenv("DATABASE_URL")
BATCH_SIZE = int(os.getenv("GDELT_ENRICHMENT_BATCH_SIZE", "100"))
POLL_INTERVAL = int(os.getenv("GDELT_ENRICHMENT_POLL_SECONDS", "300"))  # 5 minutes

def get_conn():
    """Get database connection"""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

def gdelt_to_raw_alert(event: Dict[str, Any]) -> Dict[str, Any]:
    """Convert GDELT event to raw_alerts format (minimal schema for Threat Engine input)"""
    # Generate UUID from global_event_id
    uuid = f"gdelt-{event['global_event_id']}"
    
    # Convert sql_date (YYYYMMDD) to timestamp
    sql_date_str = str(event['sql_date'])
    try:
        published = datetime.strptime(sql_date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    except:
        published = datetime.now(timezone.utc)
    
    # Extract basic metadata
    actor1 = event.get('actor1', 'Unknown')
    actor2 = event.get('actor2', 'Unknown')
    event_code = event.get('event_code', '')
    quad_class = event.get('quad_class', 0)
    goldstein = event.get('goldstein', 0) or 0
    
    # Build title
    title = f"GDELT: {actor1} → {actor2}"
    if event_code:
        title += f" ({event_code})"
    
    country = event.get('action_country', 'Unknown')
    
    # Summary with raw metrics (Threat Engine will compute final scores)
    summary = f"GDELT event: {actor1} and {actor2}. Goldstein: {goldstein}, Tone: {event.get('avg_tone', 0)}, Mentions: {event.get('num_mentions', 0)}"
    
    # Tags with rich metadata for Threat Engine context
    import json
    tags = [{
        'source': 'gdelt',
        'event_id': event['global_event_id'],
        'quad_class': quad_class,
        'event_code': event_code,
        'goldstein': goldstein,
        'avg_tone': event.get('avg_tone'),
        'num_mentions': event.get('num_mentions'),
        'num_sources': event.get('num_sources'),
        'num_articles': event.get('num_articles'),
        'actor1': actor1,
        'actor2': actor2,
    }]
    
    raw_alert = {
        'uuid': uuid,
        'published': published,
        'source': 'gdelt',
        'source_kind': 'intelligence',  # Match ACLED pattern
        'source_tag': f"country:{country}" if country and country != 'Unknown' else 'country:Unknown',
        'title': title,
        'summary': summary,
        'link': event.get('source_url') or f"https://gdeltproject.org/data/lookups/CAMEO.eventcodes.txt",
        'region': None,
        'country': country if country and country != 'Unknown' else None,
        'city': None,
        'latitude': event.get('action_lat'),
        'longitude': event.get('action_long'),
        'tags': json.dumps(tags),
    }
    
    return raw_alert

def process_batch(conn, batch_size: int = 100) -> int:
    """Process a batch of unprocessed GDELT events into raw_alerts"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Get unprocessed events with coordinates
        cur.execute("""
            SELECT global_event_id, sql_date, actor1, actor2, event_code, event_root_code,
                   quad_class, goldstein, num_mentions, num_sources, num_articles, avg_tone,
                   action_country, action_lat, action_long, source_url
            FROM gdelt_events
            WHERE processed = false
              AND action_lat IS NOT NULL
              AND action_long IS NOT NULL
              AND quad_class IN (3, 4)  -- Only conflict events
            ORDER BY sql_date DESC
            LIMIT %s
        """, (batch_size,))
        
        events = cur.fetchall()
        
        if not events:
            return 0
        
        logger.info(f"Processing {len(events)} GDELT events into raw_alerts...")
        
        processed_ids = []
        inserted_count = 0
        
        for event in events:
            try:
                raw_alert = gdelt_to_raw_alert(dict(event))
                
                # Insert into raw_alerts (Threat Engine will enrich → alerts)
                cur.execute("""
                    INSERT INTO raw_alerts (
                        uuid, published, source, source_kind, source_tag, title, summary, link,
                        region, country, city, latitude, longitude, tags
                    ) VALUES (
                        %(uuid)s, %(published)s, %(source)s, %(source_kind)s, %(source_tag)s,
                        %(title)s, %(summary)s, %(link)s, %(region)s, %(country)s, %(city)s,
                        %(latitude)s, %(longitude)s, %(tags)s::jsonb
                    )
                    ON CONFLICT (uuid) DO NOTHING
                """, raw_alert)
                
                processed_ids.append(event['global_event_id'])
                inserted_count += 1
                
            except Exception as e:
                logger.error(f"Error processing event {event['global_event_id']}: {e}")
                continue
        
        # Mark events as processed
        if processed_ids:
            cur.execute("""
                UPDATE gdelt_events
                SET processed = true
                WHERE global_event_id = ANY(%s)
            """, (processed_ids,))
        
        conn.commit()
        logger.info(f"✓ Processed {inserted_count} GDELT events into raw_alerts (will be enriched by Threat Engine)")
        
        return inserted_count
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Batch processing error: {e}")
        return 0
    finally:
        cur.close()

def run_worker():
    """Main worker loop"""
    logger.info("GDELT Enrichment Worker started")
    logger.info(f"Batch size: {BATCH_SIZE}, Poll interval: {POLL_INTERVAL}s")
    
    while True:
        try:
            conn = get_conn()
            processed = process_batch(conn, BATCH_SIZE)
            conn.close()
            
            if processed > 0:
                logger.info(f"Processed {processed} events, checking for more...")
                time.sleep(5)  # Short delay if there's more work
            else:
                logger.info(f"No unprocessed events, sleeping {POLL_INTERVAL}s...")
                time.sleep(POLL_INTERVAL)
                
        except KeyboardInterrupt:
            logger.info("Worker stopped by user")
            break
        except Exception as e:
            logger.error(f"Worker error: {e}")
            time.sleep(60)  # Wait 1 min on error

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        # One-time batch processing
        logger.info("Running one-time batch processing...")
        conn = get_conn()
        total = 0
        while True:
            processed = process_batch(conn, BATCH_SIZE)
            total += processed
            if processed == 0:
                break
        conn.close()
        logger.info(f"✓ Total processed: {total}")
    else:
        # Continuous worker
        run_worker()
