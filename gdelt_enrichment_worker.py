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

# Get database URL (Railway sets DATABASE_URL, fallback to config)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL or DATABASE_URL.startswith("sqlite"):
    try:
        from config import CONFIG
        DATABASE_URL = CONFIG.database.url
    except Exception:
        DATABASE_URL = os.getenv("DATABASE_PUBLIC_URL")

# Safeguards: Process in small batches, not aggressive polling
GDELT_ENRICHMENT_BATCH_SIZE = int(os.getenv("GDELT_ENRICHMENT_BATCH_SIZE", "100"))  # Process in small batches
GDELT_ENRICHMENT_POLL_SECONDS = int(os.getenv("GDELT_ENRICHMENT_POLL_SECONDS", "300"))  # 5 min polling (not aggressive)

BATCH_SIZE = GDELT_ENRICHMENT_BATCH_SIZE
POLL_INTERVAL = GDELT_ENRICHMENT_POLL_SECONDS

# Enable aggressive filtering (gdelt_filters.py)
GDELT_ENABLE_FILTERS = os.getenv("GDELT_ENABLE_FILTERS", "false").lower() in ("true", "1", "yes")

# COMPREHENSIVE CAMEO EVENT CODE LOOKUP - 100+ codes
CAMEO_CODES = {
    # ========== QUADCLASS 4: MATERIAL CONFLICT ==========
    
    # Category 18: Assault
    "18": "assault",
    "180": "use conventional military force",
    "181": "fight with small arms and light weapons",
    "182": "fight with artillery and tanks",
    "183": "engage in organized violent conflict",
    "1831": "engage in ethnic cleansing",
    "1832": "engage in gang warfare",
    "184": "use chemical, biological, or nuclear weapons",
    "185": "employ aerial weapons",
    "186": "violate ceasefire",
    
    # Category 19: Fight
    "19": "engage in unconventional violence",
    "190": "use unconventional mass violence",
    "191": "abduct, hijack, or take hostage",
    "192": "physically assault",
    "193": "engage in politically motivated violence",
    "194": "use violent repression",
    "195": "engage in violent protest for leadership change",
    "196": "engage in ethnic violence",
    
    # Category 20: Mass Violence
    "20": "engage in mass violence",
    "200": "use tactics of violent repression",
    "201": "kill by physical assault",
    "202": "inflict torture",
    "203": "engage in ethnic cleansing",
    "204": "use weapons of mass destruction",
    
    # ========== QUADCLASS 3: VERBAL CONFLICT ==========
    
    # Category 10: Demand
    "10": "demand",
    "100": "demand information",
    "101": "demand policy change",
    "102": "demand action",
    "103": "demand rights",
    "1031": "demand easing of administrative sanctions",
    "1032": "demand easing of blockade",
    "1033": "demand release of persons or property",
    "1034": "demand right to asylum",
    "104": "demand material cooperation",
    "1041": "demand economic aid",
    "1042": "demand military aid",
    "1043": "demand military protection",
    "1044": "demand peace talks",
    "105": "demand diplomatic cooperation",
    "1051": "demand mediation",
    "1052": "demand peace settlement",
    "106": "demand de-escalation",
    "107": "demand cessation of violence",
    
    # Category 11: Disapprove
    "11": "disapprove",
    "110": "criticize or denounce",
    "111": "accuse",
    "1111": "accuse of crime",
    "1112": "accuse of human rights abuse",
    "1113": "accuse of aggression",
    "1114": "accuse of corruption",
    "112": "blame",
    "113": "deny responsibility",
    "114": "give pessimistic comment",
    
    # Category 12: Reject
    "12": "reject",
    "120": "reject request or demand",
    "121": "reject proposal",
    "122": "reject plan or agreement",
    "123": "reject accusation",
    "124": "reject conditions",
    "125": "reject peace proposal",
    "126": "reject calls for peace talks",
    
    # Category 13: Threaten
    "13": "threaten",
    "130": "threaten non-military pressure",
    "131": "threaten blockade",
    "132": "threaten sanctions",
    "1321": "threaten economic sanctions",
    "1322": "threaten travel restrictions",
    "1323": "threaten arms embargo",
    "133": "threaten to reduce relations",
    "134": "threaten to halt negotiations",
    "135": "threaten to halt international aid",
    "136": "threaten to withdraw",
    "137": "threaten with political dissent",
    "138": "threaten to use military force",
    "1381": "threaten unconventional violence",
    "1382": "threaten with military attack",
    "1383": "threaten with nuclear weapons",
    "139": "give ultimatum",
    
    # Category 14: Protest
    "14": "protest",
    "140": "engage in political dissent",
    "141": "demonstrate or rally",
    "1411": "demonstrate for leadership change",
    "1412": "demonstrate for policy change",
    "1413": "demonstrate for rights",
    "142": "conduct hunger strike",
    "143": "conduct strikes or boycotts",
    "1431": "conduct general strike",
    "1432": "conduct labor strike",
    "1433": "conduct boycott",
    "144": "obstruct passage",
    "1441": "block road or border",
    "1442": "occupy building or area",
    "145": "protest violently",
    
    # Category 15: Exhibit Military Posture
    "15": "exhibit military posture",
    "150": "demonstrate military capability",
    "151": "conduct military exercise",
    "152": "mobilize armed forces",
    "153": "move military equipment",
    "154": "deploy peacekeepers",
    
    # Category 16: Reduce Relations
    "16": "reduce relations",
    "160": "reduce cooperation",
    "161": "reduce aid",
    "162": "halt negotiations",
    "163": "expel or withdraw",
    "1631": "expel diplomats",
    "1632": "expel organization",
    "164": "reduce or break diplomatic relations",
    
    # Category 17: Coerce
    "17": "coerce",
    "170": "seize possessions",
    "1701": "seize property",
    "1702": "confiscate assets",
    "171": "impose administrative sanctions",
    "1711": "impose blockade",
    "1712": "impose border restrictions",
    "1713": "impose curfew",
    "172": "impose economic sanctions",
    "1721": "impose embargo",
    "1722": "ban imports or exports",
    "173": "impose restrictions on political freedoms",
    "174": "arrest, detain, or charge",
    "1741": "arrest or detain",
    "1742": "charge with crime",
    "175": "expel from country",
    
    # ========== QUADCLASS 2: APPEAL (Cooperative Conflict) ==========
    
    # Category 04: Consult
    "04": "consult",
    "040": "discuss by telephone",
    "041": "make statement",
    "042": "make appeal",
    "043": "engage in negotiation",
    "044": "consult on policy",
    
    # Category 05: Engage Diplomatically
    "05": "engage diplomatically",
    "050": "engage in diplomatic cooperation",
    "051": "praise or endorse",
    "052": "defend verbally",
    "053": "rally support",
    "054": "express accord",
    
    # Category 06: Engage in Material Cooperation
    "06": "provide aid",
    "060": "cooperate",
    "061": "provide economic aid",
    "062": "provide military aid",
    "063": "provide humanitarian aid",
    "064": "provide shelter or sanctuary",
    
    # ========== QUADCLASS 1: VERBAL COOPERATION ==========
    
    # Category 01: Make Public Statement
    "01": "make public statement",
    "010": "make statement",
    "011": "decline comment",
    "012": "make pessimistic comment",
    "013": "make optimistic comment",
    
    # Category 02: Appeal
    "02": "appeal",
    "020": "make appeal",
    "021": "appeal for material cooperation",
    "022": "appeal for diplomatic cooperation",
    "023": "appeal for aid",
    "024": "appeal for change",
    
    # Category 03: Express Intent to Cooperate
    "03": "express intent to cooperate",
    "030": "express intent",
    "031": "express intent to engage in dialogue",
    "032": "express intent to settle dispute",
    "033": "express intent to meet",
    "034": "express intent to provide aid",
}

def get_conn():
    """Get database connection"""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

def get_event_description(event_code: str) -> str:
    """Translate CAMEO event code to human-readable description"""
    if not event_code:
        return "geopolitical event"
    if event_code in CAMEO_CODES:
        return CAMEO_CODES[event_code]
    root_code = event_code[:2] if len(event_code) >= 2 else event_code
    if root_code in CAMEO_CODES:
        return CAMEO_CODES[root_code]
    return "conflict event"

def get_severity_label(goldstein: float) -> str:
    """Convert Goldstein scale to plain English severity"""
    if goldstein is None:
        return "MODERATE"
    goldstein = float(goldstein)
    if goldstein <= -8:
        return "CRITICAL"
    elif goldstein <= -6:
        return "HIGH"
    elif goldstein <= -4:
        return "MODERATE"
    elif goldstein <= -2:
        return "LOW"
    else:
        return "MINIMAL"

def get_threat_category(event_code: str, quad_class: int) -> str:
    """Map CAMEO codes to user-facing threat categories"""
    if not event_code:
        return "Geopolitical Event"
    
    # Get the root category code (first 2 digits)
    root_code = event_code[:2] if len(event_code) >= 2 else event_code
    
    # QuadClass 1: Material Conflict (most severe)
    if quad_class == 1:
        if root_code == '18':  # Assault, coercion, military force
            return "Armed Conflict"
        elif root_code == '19':  # Fight, unconventional violence
            return "Terrorism / Violence"
        elif root_code == '20':  # Mass violence, genocide
            return "Mass Atrocity"
        else:
            return "Armed Conflict"  # Default for QuadClass 1
    
    # QuadClass 2: Verbal Conflict
    elif quad_class == 2:
        if root_code == '13':  # Threaten
            return "Military Threat"
        elif root_code == '14':  # Protest
            return "Civil Unrest"
        elif root_code == '15':  # Exhibit military posture
            return "Military Posture"
        elif root_code == '17':  # Coerce
            return "Coercion / Sanctions"
        else:
            return "Diplomatic Tension"
    
    # QuadClass 3: Material Cooperation
    elif quad_class == 3:
        return "International Cooperation"
    
    # QuadClass 4: Verbal Cooperation
    elif quad_class == 4:
        return "Diplomatic Activity"
    
    return "Geopolitical Event"

def should_show_on_travel_map(event_code: str, quad_class: int, goldstein: float) -> bool:
    """Filter logic for travel risk map"""
    # Only show QuadClass 1/2 (material conflict, verbal conflict)
    if quad_class not in [1, 2]:
        return False
    
    # Only show high severity
    if goldstein > -5:
        return False
    
    # Get the root category code (first 2 digits)
    root_code = event_code[:2] if event_code and len(event_code) >= 2 else event_code
    
    # EXCLUDE from travel map:
    exclude_roots = [
        # Diplomatic statements (not physical threats)
        '01', '02', '03',
        # Economic sanctions (don't affect traveler safety)
        '172', '1721', '1722',
    ]
    
    if root_code in exclude_roots or event_code in ['172', '1721', '1722', '1631', '1632', '164']:
        return False
    
    # INCLUDE on travel map: violent events, protests, military threats
    include_roots = [
        '18',  # Armed conflict
        '19',  # Violence/terrorism
        '20',  # Mass violence
        '14',  # Protests (can block travel)
        '13',  # Military threats
        '17',  # Coercion/arrests (traveler safety)
    ]
    
    if root_code in include_roots:
        return True
    
    # Default: if QuadClass 1 and severe, show it
    return quad_class == 1 and goldstein <= -6

def clean_actor(actor: str) -> Optional[str]:
    """Clean and validate actor name"""
    if not actor or actor in ["", ".", "---", "Unknown"]:
        return None
    actor = actor.strip()
    if len(actor) <= 1:
        return None
    return actor

def build_gdelt_summary(event: Dict[str, Any]) -> str:
    """Build contextual summary for threat engine enrichment"""
    
    actor1 = clean_actor(event.get('actor1', ''))
    actor2 = clean_actor(event.get('actor2', ''))
    event_code = event.get('event_code', '')
    event_description = get_event_description(event_code)
    threat_category = get_threat_category(event_code, event.get('quad_class', 0))
    
    country = event.get('action_country', 'Unknown')
    goldstein = event.get('goldstein', 0) or 0
    severity_label = get_severity_label(goldstein)
    num_articles = event.get('num_articles', 0)
    num_sources = event.get('num_sources', 0)
    
    # Build natural language summary
    parts = []
    
    # Event description with location
    if actor1 and actor2:
        base = f"{actor1} {event_description} involving {actor2}"
    elif actor1:
        base = f"{actor1} {event_description}"
    else:
        base = f"{threat_category} reported"
    
    if country and country != 'Unknown':
        base += f" in {country}"
    
    parts.append(base)
    
    # Severity assessment
    parts.append(f"Threat level: {severity_label}")
    
    # Media coverage (verification indicator)
    if num_articles > 50:
        parts.append(f"Widely reported ({num_articles} articles from {num_sources} sources)")
    elif num_articles > 10:
        parts.append(f"Confirmed by {num_sources} sources")
    elif num_articles > 0:
        parts.append(f"Limited coverage ({num_articles} reports)")
    
    # Goldstein context for threat engine
    if goldstein <= -8:
        parts.append("Extreme negative impact")
    elif goldstein <= -6:
        parts.append("Significant negative impact")
    
    return ". ".join(parts) + "."

def gdelt_to_raw_alert(event: Dict[str, Any]) -> Dict[str, Any]:
    """Convert GDELT event to raw_alerts format with proper client-facing text"""
    uuid = f"gdelt-{event['global_event_id']}"
    sql_date_str = str(event['sql_date'])
    try:
        published = datetime.strptime(sql_date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    except:
        published = datetime.now(timezone.utc)
    actor1 = clean_actor(event.get('actor1', ''))
    actor2 = clean_actor(event.get('actor2', ''))
    event_code = event.get('event_code', '')
    event_description = get_event_description(event_code)
    quad_class = event.get('quad_class', 0)
    goldstein = event.get('goldstein', 0) or 0
    severity_label = get_severity_label(goldstein)
    threat_category = get_threat_category(event_code, quad_class)
    travel_map_eligible = should_show_on_travel_map(event_code, quad_class, goldstein)
    country = event.get('action_country', 'Unknown')
    num_mentions = event.get('num_mentions', 0)
    num_articles = event.get('num_articles', 0)
    if actor1 and actor2:
        title = f"{actor1} {event_description} involving {actor2}"
    elif actor1:
        title = f"{actor1} {event_description}"
    else:
        title = f"Conflict event reported in {country}"
    
    # Use improved summary generation
    summary = build_gdelt_summary(event)
    
    import json
    tags = [{
        'source': 'gdelt',
        'event_id': event['global_event_id'],
        'quad_class': quad_class,
        'event_code': event_code,
        'event_type': event_description,
        'goldstein': goldstein,
        'severity': severity_label,
        'category': threat_category,
        'travel_map_eligible': travel_map_eligible,
        'avg_tone': event.get('avg_tone'),
        'num_mentions': num_mentions,
        'num_sources': event.get('num_sources'),
        'num_articles': num_articles,
        'actor1': actor1,
        'actor2': actor2,
    }]
    source_url = event.get('source_url')
    link = source_url if source_url and source_url.startswith('http') else None
    raw_alert = {
        'uuid': uuid,
        'published': published,
        'source': 'gdelt',
        'source_kind': 'intelligence',
        'source_tag': f"country:{country}" if country and country != 'Unknown' else 'country:Unknown',
        'title': title,
        'summary': summary,
        'link': link,
        'region': None,
        'country': country if country and country != 'Unknown' else None,
        'city': None,
        'latitude': event.get('action_lat'),
        'longitude': event.get('action_long'),
        'tags': json.dumps(tags),
        'geocoded_location_id': None,  # Will be set by geocoding if needed
    }
    return raw_alert

def process_batch(conn, batch_size: int = 100) -> int:
    """Process a batch of unprocessed GDELT events into raw_alerts"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Import geocoding service to cache coordinates and fallback geocoding
    try:
        from geocoding_service import _save_to_db as save_to_geocoding_cache, geocode
        geocoding_cache_available = True
    except ImportError:
        logger.warning("geocoding_service not available - skipping coordinate cache")
        geocoding_cache_available = False
        geocode = None
    
    try:
        # Get unprocessed events (don't require coordinates - we'll geocode if missing/invalid)
        # Smart prioritization: high-severity events first, then by recency
        cur.execute("""
            SELECT global_event_id, sql_date, actor1, actor2, event_code, event_root_code,
                   quad_class, goldstein, num_mentions, num_sources, num_articles, avg_tone,
                   action_country, action_lat, action_long, source_url
            FROM gdelt_events
            WHERE processed = false
              AND quad_class IN (3, 4)  -- Only conflict events
            ORDER BY 
                CASE 
                    WHEN goldstein <= -8 THEN 1  -- Critical severity first
                    WHEN goldstein <= -5 THEN 2  -- High severity
                    WHEN goldstein <= -3 THEN 3  -- Moderate severity
                    ELSE 4                       -- Lower severity
                END,
                num_sources DESC,  -- More widely reported events prioritized
                sql_date DESC      -- Most recent within same severity tier
            LIMIT %s
        """, (batch_size,))
        
        events = cur.fetchall()
        
        if not events:
            return 0
        
        logger.info(f"Processing {len(events)} GDELT events into raw_alerts...")
        
        processed_ids = []
        inserted_count = 0
        filtered_count = 0
        
        for event in events:
            try:
                # Apply aggressive filtering if enabled (before conversion to raw_alert)
                if GDELT_ENABLE_FILTERS:
                    try:
                        from gdelt_filters import should_ingest_gdelt_event
                        if not should_ingest_gdelt_event(dict(event), stage="enrichment"):
                            filtered_count += 1
                            processed_ids.append(event['global_event_id'])  # Mark as processed to avoid reprocessing
                            continue
                    except ImportError:
                        logger.warning("[gdelt_enrichment] gdelt_filters.py not found; filter disabled")
                
                raw_alert = gdelt_to_raw_alert(dict(event))
                
                # Validate and fix coordinates
                lat = raw_alert.get('latitude')
                lon = raw_alert.get('longitude')
                country = raw_alert.get('country')
                
                # Check if coordinates are invalid (lon=0 is GDELT's "unknown" marker)
                coords_invalid = (
                    lat is None or lon is None or
                    lon == 0.0 or  # GDELT uses 0 for unknown longitude
                    lon < -180 or lon > 180 or
                    lat < -90 or lat > 90
                )
                
                geocoded_location_id = None
                
                # If coordinates invalid, try geocoding the country
                if coords_invalid and country and geocoding_cache_available and geocode:
                    try:
                        logger.info(f"Geocoding country '{country}' for event {event['global_event_id']} (GDELT coords invalid: lon={lon}, lat={lat})")
                        geo_result = geocode(country)
                        
                        if geo_result and geo_result.get('lat') and geo_result.get('lon'):
                            # Use geocoded coordinates
                            raw_alert['latitude'] = geo_result['lat']
                            raw_alert['longitude'] = geo_result['lon']
                            lat = geo_result['lat']
                            lon = geo_result['lon']
                            logger.info(f"✓ Geocoded {country} → ({lon:.4f}, {lat:.4f})")
                        else:
                            logger.warning(f"Geocoding failed for country: {country}")
                            # Set to None so we don't display invalid markers
                            raw_alert['latitude'] = None
                            raw_alert['longitude'] = None
                    except Exception as e:
                        logger.error(f"Geocoding error for {country}: {e}")
                        raw_alert['latitude'] = None
                        raw_alert['longitude'] = None
                
                # Cache valid coordinates in geocoded_locations
                if geocoding_cache_available and lat and lon and country:
                    # Validate coordinates are actually valid now
                    if -180 <= lon <= 180 and -90 <= lat <= 90 and lon != 0.0:
                        try:
                            location_text = f"{country} ({lat:.4f}, {lon:.4f})"
                            
                            geo_data = {
                                'lat': lat,
                                'lon': lon,
                                'country_code': country,
                                'admin_level_1': None,
                                'admin_level_2': None,
                                'confidence': 7,
                                'source': 'gdelt'
                            }
                            
                            save_to_geocoding_cache(location_text, geo_data)
                            logger.debug(f"Cached coordinates for {country}")
                        except Exception as e:
                            logger.debug(f"Failed to cache coordinates: {e}")
                
                # Insert into raw_alerts (Threat Engine will enrich → alerts)
                cur.execute("""
                    INSERT INTO raw_alerts (
                        uuid, published, source, source_kind, source_tag, title, summary, link,
                        region, country, city, latitude, longitude, tags, geocoded_location_id
                    ) VALUES (
                        %(uuid)s, %(published)s, %(source)s, %(source_kind)s, %(source_tag)s,
                        %(title)s, %(summary)s, %(link)s, %(region)s, %(country)s, %(city)s,
                        %(latitude)s, %(longitude)s, %(tags)s::jsonb, %(geocoded_location_id)s
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
        
        # Cost estimation: Track alerts processed (LLM enrichment happens in threat_engine)
        estimated_llm_calls = inserted_count  # Each alert will trigger 1 LLM call in threat_engine
        estimated_cost_usd = estimated_llm_calls * 0.002  # ~$0.002 per LLM call
        
        logger.info(f"✓ Batch enrichment complete: {inserted_count} inserted, {filtered_count} filtered (${estimated_cost_usd:.4f} estimated LLM cost)")
        
        logger.info(
            "gdelt_enrichment_cost_estimate",
            alerts_processed=inserted_count,
            estimated_llm_calls=estimated_llm_calls,
            estimated_cost_usd=round(estimated_cost_usd, 4)
        )
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
