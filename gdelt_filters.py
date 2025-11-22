"""
gdelt_filters.py

Aggressive GDELT filtering to reduce noise and focus on high-signal conflict events.
Can be applied at ingest (gdelt_events) or enrichment (raw_alerts) stages.
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger("gdelt_filters")

# Environment-configurable thresholds (for easy tuning in production)
# RELAXED THRESHOLDS: More permissive to allow broader event coverage
MIN_GOLDSTEIN = float(os.getenv("GDELT_MIN_GOLDSTEIN", "-2.0"))  # Relaxed: -2.0 (moderately negative)
MIN_MENTIONS = int(os.getenv("GDELT_MIN_MENTIONS", "2"))  # Relaxed: 2 sources (down from 3)
MIN_TONE = float(os.getenv("GDELT_MIN_TONE", "-2.0"))  # Relaxed: -2.0 (moderately negative tone)
MAX_AGE_HOURS = int(os.getenv("GDELT_MAX_AGE_HOURS", "168"))  # Relaxed: 168h (7 days, up from 3 days)
REQUIRE_SOURCE_URL = os.getenv("GDELT_REQUIRE_SOURCE_URL", "false").lower() in ("true", "1", "yes")
REQUIRE_PRECISE_COORDS = os.getenv("GDELT_REQUIRE_PRECISE_COORDS", "false").lower() in ("true", "1", "yes")

# CAMEO event code whitelist (expanded for better coverage)
# Includes: threats, protests, assaults, fights, and high-impact verbal conflicts
ALLOWED_EVENT_CODES = [
    # Category 13: Threaten (verbal threats)
    "13",    # Generic threat
    "130",   # Threaten
    "131",   # Threaten with force
    "1311",  # Threaten with military force
    "1312",  # Threaten with nuclear weapons
    "132",   # Threaten to occupy territory
    "133",   # Threaten to blockade
    "134",   # Threaten to use unconventional violence
    "1341",  # Threaten with violence
    "1343",  # Threaten with terror attack
    "138",   # Threaten to reduce relations
    
    # Category 14: Protest (high-signal dissent)
    "14",    # Generic protest
    "140",   # Engage in political dissent
    "141",   # Demonstrate or rally
    "1411",  # Demonstrate for leadership change
    "1412",  # Demonstrate for policy change
    "1413",  # Demonstrate for rights
    "143",   # Conduct strikes or boycotts
    "1431",  # Conduct general strike
    "1432",  # Conduct labor strike
    "144",   # Obstruct passage
    "1441",  # Block road or border
    "1442",  # Occupy building or area
    "145",   # Protest violently (riot)
    
    # Category 17: Coerce (force without violence)
    "17",    # Generic coerce
    "170",   # Coerce
    "171",   # Seize or damage property
    "1711",  # Confiscate property
    "172",   # Impose administrative sanctions
    "173",   # Arrest, detain
    "174",   # Expel or deport
    
    # Category 18: Assault
    "18",    # Generic assault
    "180",   # Use unconventional violence
    "181",   # Abduct, hijack, take hostage
    "1811",  # Kidnap
    "1812",  # Hijack vehicle or plane
    "1813",  # Take hostage
    "182",   # Use physical assault
    "1821",  # Sexually assault
    "1822",  # Torture
    "1823",  # Kill by physical assault
    "183",   # Conduct suicide bombing
    "184",   # Use weapons of mass destruction
    
    # Category 19: Fight (conventional military force)
    "19",    # Generic fight
    "190",   # Use conventional military force
    "191",   # Impose blockade
    "192",   # Occupy territory
    "193",   # Fight with small arms and light weapons
    "194",   # Fight with artillery and tanks
    "195",   # Employ aerial weapons
    "196",   # Violate ceasefire
    
    # Category 20: Unconventional Mass Violence
    "20",    # Generic mass violence
    "200",   # Use tactics of violent repression
    "201",   # Kill by physical assault
    "202",   # Inflict torture
    "203",   # Engage in ethnic cleansing
    "204",   # Use weapons of mass destruction
]

# QuadClass filters: Focus on material conflict (4) and exclude cooperation (1, 3)
ALLOWED_QUAD_CLASSES = [2, 4]  # Verbal conflict (2), Material conflict (4)
EXCLUDED_QUAD_CLASSES = [1, 3]  # Verbal cooperation (1), Material cooperation (3)


def should_ingest_gdelt_event(event: Dict[str, Any], stage: str = "ingest") -> bool:
    """
    Aggressive GDELT filtering to remove noise and focus on high-signal events.
    
    Args:
        event: GDELT event dict (can be raw row mapping or enriched dict)
        stage: "ingest" (during gdelt_ingest) or "enrichment" (during gdelt_enrichment_worker)
    
    Returns:
        True if event passes all filters and should be ingested/processed
    """
    
    # 1. Source URL check (optional, expensive for bulk ingestion)
    if REQUIRE_SOURCE_URL and stage == "enrichment":
        source_url = event.get('source_url')
        if not source_url or source_url.strip() == "":
            logger.debug(f"[filter] Rejected: no source URL (event_id={event.get('global_event_id')})")
            return False
    
    # 2. Coordinate quality check
    lat = event.get('action_lat') or event.get('ActionGeo_Lat')
    lon = event.get('action_long') or event.get('ActionGeo_Long')
    
    if lat is None or lon is None:
        logger.debug(f"[filter] Rejected: missing coordinates (event_id={event.get('global_event_id')})")
        return False
    
    # Cast to float safely
    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        logger.debug(f"[filter] Rejected: invalid coordinate format (event_id={event.get('global_event_id')})")
        return False
    
    # Reject (0,0) coordinates (likely country centroid or missing data)
    if REQUIRE_PRECISE_COORDS and (lat == 0.0 and lon == 0.0):
        logger.debug(f"[filter] Rejected: (0,0) coordinates (event_id={event.get('global_event_id')})")
        return False
    
    # Sanity check: valid lat/lon ranges
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        logger.debug(f"[filter] Rejected: out-of-range coordinates lat={lat}, lon={lon} (event_id={event.get('global_event_id')})")
        return False
    
    # 3. Goldstein scale: Only highly negative events
    goldstein = event.get('goldstein', 0)
    try:
        goldstein = float(goldstein) if goldstein is not None else 0.0
    except (ValueError, TypeError):
        goldstein = 0.0
    
    if goldstein > MIN_GOLDSTEIN:
        logger.debug(f"[filter] Rejected: goldstein {goldstein} > {MIN_GOLDSTEIN} (event_id={event.get('global_event_id')})")
        return False
    
    # 4. Media mentions: Require multiple sources for verification
    num_mentions = event.get('num_mentions', 0)
    try:
        num_mentions = int(num_mentions) if num_mentions is not None else 0
    except (ValueError, TypeError):
        num_mentions = 0
    
    if num_mentions < MIN_MENTIONS:
        logger.debug(f"[filter] Rejected: only {num_mentions} mentions (min {MIN_MENTIONS}) (event_id={event.get('global_event_id')})")
        return False
    
    # 5. Average tone: Must be significantly negative
    avg_tone = event.get('avg_tone', 0)
    try:
        avg_tone = float(avg_tone) if avg_tone is not None else 0.0
    except (ValueError, TypeError):
        avg_tone = 0.0
    
    if avg_tone > MIN_TONE:
        logger.debug(f"[filter] Rejected: avg_tone {avg_tone} > {MIN_TONE} (event_id={event.get('global_event_id')})")
        return False
    
    # 6. CAMEO event code whitelist (violence/conflict/protest only)
    event_code = str(event.get('event_code', ''))
    if not event_code:
        logger.debug(f"[filter] Rejected: no event_code (event_id={event.get('global_event_id')})")
        return False
    
    # Check if event_code starts with any allowed prefix
    code_allowed = any(event_code.startswith(code) for code in ALLOWED_EVENT_CODES)
    if not code_allowed:
        logger.debug(f"[filter] Rejected: event_code '{event_code}' not in whitelist (event_id={event.get('global_event_id')})")
        return False
    
    # 7. QuadClass filter: Exclude cooperation classes
    quad_class = event.get('quad_class', 0)
    try:
        quad_class = int(quad_class) if quad_class is not None else 0
    except (ValueError, TypeError):
        quad_class = 0
    
    if quad_class in EXCLUDED_QUAD_CLASSES:
        logger.debug(f"[filter] Rejected: quad_class {quad_class} is excluded (cooperation) (event_id={event.get('global_event_id')})")
        return False
    
    if quad_class not in ALLOWED_QUAD_CLASSES:
        logger.debug(f"[filter] Rejected: quad_class {quad_class} not in allowed list (event_id={event.get('global_event_id')})")
        return False
    
    # 8. Event age check (optional, only at enrichment stage to avoid clock skew issues)
    if stage == "enrichment" and MAX_AGE_HOURS > 0:
        sql_date = event.get('sql_date')
        if sql_date:
            try:
                sql_date_str = str(sql_date)
                event_date = datetime.strptime(sql_date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - event_date).total_seconds() / 3600
                if age_hours > MAX_AGE_HOURS:
                    logger.debug(f"[filter] Rejected: event too old ({age_hours:.1f}h > {MAX_AGE_HOURS}h) (event_id={event.get('global_event_id')})")
                    return False
            except Exception as e:
                logger.warning(f"[filter] Could not parse sql_date {sql_date}: {e}")
    
    # All filters passed
    logger.debug(f"[filter] ACCEPTED: event_id={event.get('global_event_id')}, code={event_code}, goldstein={goldstein}, mentions={num_mentions}, tone={avg_tone}")
    return True


def get_filter_stats() -> Dict[str, Any]:
    """Return current filter configuration for monitoring/debugging"""
    return {
        "min_goldstein": MIN_GOLDSTEIN,
        "min_mentions": MIN_MENTIONS,
        "min_tone": MIN_TONE,
        "max_age_hours": MAX_AGE_HOURS,
        "require_source_url": REQUIRE_SOURCE_URL,
        "require_precise_coords": REQUIRE_PRECISE_COORDS,
        "allowed_event_codes_count": len(ALLOWED_EVENT_CODES),
        "allowed_quad_classes": ALLOWED_QUAD_CLASSES,
        "excluded_quad_classes": EXCLUDED_QUAD_CLASSES
    }
