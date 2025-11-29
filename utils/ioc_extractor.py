"""
IOC extraction patterns for social media handles and URLs.
Integrates with threat engine enrichment pipeline.
"""

import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Social media patterns
INSTAGRAM_PATTERNS = [
    r'(?:instagram\.com|ig\.me)/([a-zA-Z0-9._]{1,30})',  # URLs
    r'@([a-zA-Z0-9._]{1,30})',  # @handles
    r'(?:^|\s)ig:([a-zA-Z0-9._]{1,30})',  # ig:username mentions
]

FACEBOOK_PATTERNS = [
    r'(?:facebook\.com|fb\.me)/([a-zA-Z0-9.]{1,50})',  # Profile/page URLs
    r'(?:facebook\.com|fb\.com)/pages/[^/]+/(\d+)',  # Page IDs
]

TWITTER_PATTERNS = [
    r'(?:twitter\.com|x\.com)/([a-zA-Z0-9_]{1,15})',  # Profile URLs
    r'@([a-zA-Z0-9_]{1,15})',  # @handles
]

TELEGRAM_PATTERNS = [
    r't\.me/([a-zA-Z0-9_]{5,32})',  # Channel/group handles
    r'@([a-zA-Z0-9_]{5,32})',  # @handles in text
]


def extract_social_media_iocs(text: str) -> List[Dict[str, str]]:
    """
    Extract social media handles and URLs from alert text.
    
    Args:
        text: Alert title/summary combined text
        
    Returns:
        List of IOC dicts with 'type', 'platform', 'value', 'url'
    """
    iocs = []
    seen = set()  # Deduplicate
    
    if not text:
        return iocs
    
    # Instagram
    for pattern in INSTAGRAM_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            handle = match.group(1).lower()
            key = ('instagram', handle)
            if key not in seen:
                seen.add(key)
                iocs.append({
                    'type': 'social_media',
                    'platform': 'instagram',
                    'value': handle,
                    'url': f'https://instagram.com/{handle}'
                })
    
    # Facebook
    for pattern in FACEBOOK_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            identifier = match.group(1)
            key = ('facebook', identifier)
            if key not in seen:
                seen.add(key)
                # Construct full URL from context
                if identifier.isdigit():
                    url = f'https://www.facebook.com/pages/{identifier}'
                else:
                    url = f'https://www.facebook.com/{identifier}'
                iocs.append({
                    'type': 'social_media',
                    'platform': 'facebook',
                    'value': identifier,
                    'url': url
                })
    
    # Twitter/X (optional - not currently scraped)
    for pattern in TWITTER_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            handle = match.group(1).lower()
            key = ('twitter', handle)
            if key not in seen:
                seen.add(key)
                iocs.append({
                    'type': 'social_media',
                    'platform': 'twitter',
                    'value': handle,
                    'url': f'https://x.com/{handle}'
                })
    
    # Telegram (optional)
    for pattern in TELEGRAM_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            handle = match.group(1).lower()
            key = ('telegram', handle)
            if key not in seen:
                seen.add(key)
                iocs.append({
                    'type': 'social_media',
                    'platform': 'telegram',
                    'value': handle,
                    'url': f'https://t.me/{handle}'
                })
    
    return iocs


def enrich_alert_with_socmint(alert: dict, iocs: List[Dict[str, str]]) -> dict:
    """
    Enrich alert with SOCMINT data for extracted social media IOCs.
    
    Args:
        alert: Alert dict to enrich
        iocs: List of social media IOCs from extract_social_media_iocs
        
    Returns:
        Alert dict with 'enrichments.osint' populated
    """
    if not iocs:
        return alert
    
    try:
        from socmint_service import SocmintService
        socmint = SocmintService()
    except Exception as e:
        logger.warning(f"SOCMINT service unavailable: {e}")
        return alert
    
    alert.setdefault('enrichments', {})
    alert['enrichments'].setdefault('osint', [])
    
    for ioc in iocs:
        platform = ioc['platform']
        identifier = ioc['value']
        
        # Only scrape Instagram and Facebook for now
        if platform not in ['instagram', 'facebook']:
            continue
        
        try:
            # Use cached value if available (2-hour TTL)
            cached = socmint.get_cached_socmint_data(platform, identifier, ttl_minutes=120)
            if cached.get('success'):
                result = cached
                logger.info(f"[SOCMINT Enrichment] Using cached data: {platform}/{identifier}")
            else:
                logger.info(f"[SOCMINT Enrichment] Cache miss, initiating fresh scrape: {platform}/{identifier}")
                if platform == 'instagram':
                    result = socmint.run_instagram_scraper(identifier, results_limit=10)
                elif platform == 'facebook':
                    result = socmint.run_facebook_scraper(ioc['url'], results_limit=10)
                else:
                    continue
            
            if result.get('success'):
                osint_data = {
                    'platform': platform,
                    'identifier': identifier,
                    'url': ioc['url'],
                    'data': result['data'],
                    'scraped_at': result.get('scraped_at')
                }
                alert['enrichments']['osint'].append(osint_data)
                
                # Persist to DB for correlation if fresh scrape
                if not cached.get('success'):
                    socmint.save_socmint_data(platform, identifier, result['data'])
                
                logger.info(f"SOCMINT enriched: {platform}/{identifier} for alert {alert.get('uuid', 'N/A')}")
            else:
                logger.warning(f"[SOCMINT Enrichment] Scrape failed: {platform}/{identifier} - {result.get('error')}")
                
        except Exception as e:
            logger.error(f"[SOCMINT Enrichment] Error for {platform}/{identifier}: {e}", exc_info=True)
    
    # Log enrichment summary
    osint_count = len(alert['enrichments'].get('osint', []))
    if osint_count > 0:
        logger.info(f"[SOCMINT Enrichment] Completed for alert {alert.get('uuid', 'N/A')}: "
                   f"{osint_count} OSINT entries added")
    
    return alert
