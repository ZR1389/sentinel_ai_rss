# acled_collector.py — ACLED Intelligence Collector for Sentinel AI
# Fetches conflict/political violence events from ACLED API and writes to raw_alerts table
# Runs alongside RSS processor as separate intelligence source

from __future__ import annotations
import os
import json
import csv
import requests
from datetime import datetime, timedelta
from io import StringIO
from typing import List, Dict, Any, Optional

# Structured logging
from logging_config import get_logger, get_metrics_logger
logger = get_logger("acled_collector")
metrics = get_metrics_logger("acled_collector")

# Database utilities (matches your system)
try:
    from db_utils import execute, fetch_all
except ImportError:
    logger.error("db_utils not available - ACLED collector cannot persist data")
    execute = None
    fetch_all = None

# Centralized configuration
try:
    from config import CONFIG
except ImportError:
    logger.error("config module not available - using fallback env vars")
    class FallbackConfig:
        acled_email = os.getenv("ACLED_EMAIL", "")
        acled_password = os.getenv("ACLED_PASSWORD", "")
        database_url = os.getenv("DATABASE_URL", "")
    CONFIG = type('obj', (object,), {
        'acled': FallbackConfig(),
        'database': type('obj', (object,), {'url': os.getenv("DATABASE_URL", "")})()
    })()

# ACLED API endpoints (from official documentation)
ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_API_BASE = "https://acleddata.com/api/acled/read"  # Base URL for ACLED data endpoint


def get_acled_token() -> str:
    """
    Authenticate with ACLED OAuth and retrieve access token.
    
    ACLED API requires 'username' (not 'email') parameter with email value.
    
    Returns:
        Access token string
        
    Raises:
        requests.HTTPError: If authentication fails
    """
    email = CONFIG.acled.acled_email if hasattr(CONFIG, 'acled') else os.getenv("ACLED_EMAIL", "")
    password = CONFIG.acled.acled_password if hasattr(CONFIG, 'acled') else os.getenv("ACLED_PASSWORD", "")
    
    if not email or not password:
        raise ValueError("ACLED_EMAIL and ACLED_PASSWORD must be set in environment")
    
    logger.info("authenticating_with_acled", email=email)
    
    try:
        # ACLED OAuth2 - requires username, password, grant_type, and client_id
        response = requests.post(
            ACLED_TOKEN_URL,
            data={
                "username": email,
                "password": password,
                "grant_type": "password",
                "client_id": "acled"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        logger.info("acled_authentication_success")
        return token
    except requests.exceptions.RequestException as e:
        logger.error("acled_authentication_failed", error=str(e), status_code=getattr(e.response, 'status_code', None))
        # Log response body for debugging
        if hasattr(e, 'response') and e.response is not None:
            logger.error("acled_auth_response_body", body=e.response.text[:500])
        raise


def fetch_acled_events(
    token: str,
    countries: Optional[List[str]] = None,
    event_date: Optional[str] = None,
    days_back: int = 1
) -> List[Dict[str, Any]]:
    """
    Fetch ACLED events for specified countries and date range.
    
    Args:
        token: ACLED OAuth access token
        countries: List of country names (e.g., ["Nigeria", "Kenya"])
        event_date: Specific date in YYYY-MM-DD format (overrides days_back)
        days_back: Number of days back from today (default: 1 for yesterday)
        
    Returns:
        List of event dictionaries parsed from CSV
    """
    if event_date:
        target_date = event_date
    else:
        target_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    # Default to high-risk African countries if none specified
    if not countries:
        countries = [
            "Nigeria", "Somalia", "Democratic Republic of Congo",
            "South Sudan", "Ethiopia", "Mali", "Burkina Faso"
        ]
    
    logger.info(
        "fetching_acled_events",
        countries=countries,
        event_date=target_date,
        days_back=days_back
    )
    
    all_events = []
    
    for country in countries:
        try:
            # ACLED API: Bearer token authorization with query parameters
            response = requests.get(
                ACLED_API_BASE,
                params={
                    "_format": "json",  # Request JSON format
                    "country": country,
                    "event_date": target_date,
                    "limit": 500
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=60
            )
            response.raise_for_status()
            
            # Parse JSON response
            data = response.json()
            events = data.get("data", []) if isinstance(data, dict) else data
            
            logger.info(
                "acled_country_fetch_success",
                country=country,
                event_count=len(events)
            )
            
            all_events.extend(events)
            
        except requests.exceptions.RequestException as e:
            logger.error(
                "acled_country_fetch_failed",
                country=country,
                error=str(e)
            )
            # Continue with other countries even if one fails
            continue
    
    logger.info("acled_fetch_complete", total_events=len(all_events))
    return all_events


def write_acled_to_raw_alerts(events: List[Dict[str, Any]]) -> int:
    """
    Write ACLED events to raw_alerts table.
    
    Matches your system's raw_alerts schema:
    - uuid: unique identifier (acled:{event_id_cnty})
    - title: event type and sub-type
    - summary: ACLED notes field
    - source: "acled"
    - published: event_date
    - latitude/longitude: coordinates
    - country: country name
    - tags: JSON array with event metadata
    
    Args:
        events: List of ACLED event dictionaries
        
    Returns:
        Number of events inserted (excludes duplicates)
    """
    if not execute:
    
            # Import geocoding service to cache coordinates
            try:
                from geocoding_service import _save_to_db as save_to_geocoding_cache
                geocoding_cache_available = True
            except ImportError:
                logger.warning("geocoding_service not available - skipping coordinate cache")
                geocoding_cache_available = False
        logger.error("db_utils.execute not available - cannot persist ACLED data")
        return 0
    
    if not events:
        logger.warning("no_acled_events_to_write")
        return 0
    
    inserted_count = 0
    skipped_no_coords = 0
    
    for event in events:
        # Skip events without coordinates (required for threat mapping)
        if not event.get("latitude") or not event.get("longitude"):
            skipped_no_coords += 1
            continue
        
        try:
            # Generate unique UUID for ACLED events
            event_id = event.get("event_id_cnty", "")
            if not event_id:
                logger.warning("acled_event_missing_id", event=event)
                continue
            
            uuid = f"acled:{event_id}"
            
            # Build title from event type and sub-type
            event_type = event.get("event_type", "Unknown Event")
            sub_event_type = event.get("sub_event_type", "")
            title = f"{event_type}: {sub_event_type}" if sub_event_type else event_type
            
            # Summary from notes
            summary = event.get("notes", "")
            
            # Published date
            event_date_str = event.get("event_date", "")
            try:
                published = datetime.strptime(event_date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                published = datetime.utcnow()
            
            # Coordinates
            try:
                latitude = float(event.get("latitude"))
                longitude = float(event.get("longitude"))
            
                        # Cache coordinates in geocoded_locations for future proximity searches
                        geocoded_location_id = None
                        if geocoding_cache_available and latitude and longitude:
                            try:
                                # Create location text from available fields
                                location_parts = [p for p in [
                                    event.get("location"),
                                    event.get("admin2"),
                                    event.get("admin1"),
                                    event.get("country")
                                ] if p]
                                location_text = ", ".join(location_parts) if location_parts else None
                    
                                if location_text:
                                    result = save_to_geocoding_cache(
                                        location=location_text,
                                        lat=latitude,
                                        lon=longitude,
                                        country_code=event.get("iso"),
                                        admin1=event.get("admin1"),
                                        admin2=event.get("admin2"),
                                        confidence=9,  # High confidence - from ACLED API
                                        source="acled"
                                    )
                                    if result:
                                        geocoded_location_id = result.get('location_id')
                            except Exception as e:
                                logger.debug(f"Failed to cache ACLED coordinates: {e}")
            except (ValueError, TypeError):
                skipped_no_coords += 1
                continue
            
            # Country
            country = event.get("country", "")
            
            # Region/city (admin levels)
            region = event.get("admin1", "")
            city = event.get("admin2", "")
            
            # Tags: store rich ACLED metadata
            tags = [
                {
                    "source": "acled",
                    "acled_id": event_id,
                    "event_type": event.get("event_type"),
                    "sub_event_type": event.get("sub_event_type"),
                    "actor1": event.get("actor1"),
                    "actor2": event.get("actor2"),
                    "fatalities": int(event.get("fatalities", 0)) if event.get("fatalities") else 0,
                    "admin1": event.get("admin1"),
                    "admin2": event.get("admin2"),
                    "admin3": event.get("admin3"),
                    "location": event.get("location"),
                    "source_scale": event.get("source_scale"),
                    "inter1": event.get("inter1"),
                    "inter2": event.get("inter2"),
                    "interaction": event.get("interaction"),
                    "civilian_targeting": event.get("civilian_targeting"),
                    "timestamp": int(event.get("timestamp", 0))
                }
            ]
            
            # Insert into raw_alerts (ON CONFLICT DO NOTHING prevents duplicates)
            query = """
                INSERT INTO raw_alerts (
                    uuid,
                    title,
                    summary,
                    source,
                    published,
                    latitude,
                    longitude,
                    country,
                    region,
                    city,
                    tags,
                    source_tag,
                    source_kind,
                    geocoded_location_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s
                )
                ON CONFLICT (uuid) DO NOTHING
            """
            
            execute(query, (
                uuid,
                title,
                summary,
                "acled",
                published,
                latitude,
                longitude,
                country,
                region,
                city,
                json.dumps(tags),
                f"country:{country}",  # source_tag for filtering
                "intelligence"  # source_kind
                            geocoded_location_id,
            ))
            
            inserted_count += 1
            
        except Exception as e:
            logger.error(
                "acled_event_insert_failed",
                event_id=event.get("event_id_cnty"),
                error=str(e)
            )
            continue
    
    if skipped_no_coords > 0:
        logger.warning(
            "acled_events_skipped_no_coordinates",
            count=skipped_no_coords
        )
    
    logger.info(
        "acled_write_complete",
        inserted=inserted_count,
        skipped=skipped_no_coords,
        total=len(events)
    )
    
    metrics.info(
        "acled_collection_metrics",
        events_fetched=len(events),
        events_inserted=inserted_count,
        events_skipped=skipped_no_coords
    )
    
    return inserted_count


def run_acled_collector(
    countries: Optional[List[str]] = None,
    days_back: int = 1
) -> Dict[str, Any]:
    """
    Main entrypoint for ACLED collection workflow.
    
    Args:
        countries: List of countries to fetch (default: high-risk African nations)
        days_back: Number of days back to fetch (default: 1 for yesterday)
        
    Returns:
        Result dictionary with stats
    """
    start_time = datetime.utcnow()
    
    logger.info(
        "acled_collector_started",
        countries=countries,
        days_back=days_back,
        timestamp=start_time.isoformat()
    )
    
    try:
        # 1. Authenticate
        token = get_acled_token()
        
        # 2. Fetch events
        events = fetch_acled_events(token, countries=countries, days_back=days_back)
        
        if not events:
            logger.warning("no_acled_events_fetched")
            return {
                "success": True,
                "events_fetched": 0,
                "events_inserted": 0,
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
            }
        
        # 3. Write to raw_alerts
        inserted = write_acled_to_raw_alerts(events)
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        logger.info(
            "acled_collector_completed",
            events_fetched=len(events),
            events_inserted=inserted,
            duration_seconds=duration
        )
        
        return {
            "success": True,
            "events_fetched": len(events),
            "events_inserted": inserted,
            "duration_seconds": duration
        }
        
    except Exception as e:
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        logger.error(
            "acled_collector_failed",
            error=str(e),
            duration_seconds=duration,
            exc_info=True
        )
        
        return {
            "success": False,
            "error": str(e),
            "duration_seconds": duration
        }


if __name__ == "__main__":
    """
    Standalone execution for testing or cron jobs.
    
    Usage:
        python acled_collector.py
        
    Or with custom countries:
        ACLED_COUNTRIES="Nigeria,Kenya,Somalia" python acled_collector.py
    """
    # Allow country override via env var
    countries_env = os.getenv("ACLED_COUNTRIES", "")
    countries = [c.strip() for c in countries_env.split(",") if c.strip()] if countries_env else None
    
    result = run_acled_collector(countries=countries)
    
    if result["success"]:
        print(f"✓ ACLED collector completed successfully")
        print(f"  Events fetched: {result['events_fetched']}")
        print(f"  Events inserted: {result['events_inserted']}")
        print(f"  Duration: {result['duration_seconds']:.2f}s")
    else:
        print(f"✗ ACLED collector failed: {result.get('error')}")
        exit(1)
