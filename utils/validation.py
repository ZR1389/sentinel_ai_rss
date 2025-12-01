# validation.py - Input validation for Sentinel AI alerts and data
from typing import Dict, Any, List, Optional, Union, Tuple
import uuid as _uuid
from datetime import datetime
import re
from core.logging_config import get_logger

logger = get_logger("validation")

def validate_alert(alert: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate alert structure and fix common issues.
    
    Args:
        alert: Raw alert dictionary to validate
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
        
    Side Effects:
        - May auto-fix UUID if invalid
        - May normalize field types where possible
    """
    
    if not isinstance(alert, dict):
        return False, f"Alert must be dictionary, got {type(alert)}"
    
    # Check required fields
    required_fields = ["uuid", "title", "summary"]
    for field in required_fields:
        if field not in alert:
            return False, f"Missing required field: {field}"
        
        if not isinstance(alert[field], str):
            # Try to convert to string if possible
            try:
                alert[field] = str(alert[field]) if alert[field] is not None else ""
            except Exception:
                return False, f"Field {field} must be string-convertible, got {type(alert[field])}"
    
    # Validate and fix UUID format
    # Accept both UUID4 format and SHA1 hash format (40 hex chars)
    uuid_val = alert.get("uuid", "")
    is_valid_uuid = False
    
    # Check if it's a valid UUID4 format
    try:
        _uuid.UUID(uuid_val)
        is_valid_uuid = True
    except (ValueError, AttributeError, TypeError):
        pass
    
    # Also accept SHA1 hash format (40 hex characters) used by RSS processor
    if not is_valid_uuid and isinstance(uuid_val, str) and len(uuid_val) == 40:
        try:
            int(uuid_val, 16)  # Check if it's valid hex
            is_valid_uuid = True
        except (ValueError, TypeError):
            pass
    
    if not is_valid_uuid:
        # Generate new UUID if invalid
        original_uuid = alert.get("uuid")
        alert["uuid"] = str(_uuid.uuid4())
        logger.warning("uuid_auto_generated", 
                      original_uuid=original_uuid, 
                      new_uuid=alert["uuid"])
    
    # Validate datetime fields
    datetime_fields = ["published", "created_at", "updated_at"]
    for field in datetime_fields:
        if field in alert and alert[field] is not None:
            if not isinstance(alert[field], (str, datetime)):
                try:
                    # Try to convert to string
                    alert[field] = str(alert[field])
                except Exception:
                    return False, f"Field {field} must be string or datetime, got {type(alert[field])}"
    
    # Validate and sanitize text fields
    text_fields = ["title", "summary", "description", "content"]
    for field in text_fields:
        if field in alert and alert[field] is not None:
            if not isinstance(alert[field], str):
                try:
                    alert[field] = str(alert[field])
                except Exception:
                    return False, f"Field {field} must be string-convertible"
            
            # Basic sanitization - remove excessive whitespace
            alert[field] = re.sub(r'\s+', ' ', alert[field]).strip()
            
            # Check length limits
            max_lengths = {"title": 500, "summary": 2000, "description": 5000, "content": 10000}
            if field in max_lengths and len(alert[field]) > max_lengths[field]:
                logger.warning("field_truncated", 
                             field=field, 
                             original_length=len(alert[field]),
                             max_length=max_lengths[field])
                alert[field] = alert[field][:max_lengths[field]]
    
    # Validate numeric fields
    numeric_fields = ["latitude", "longitude", "score", "confidence", "severity"]
    for field in numeric_fields:
        if field in alert and alert[field] is not None:
            try:
                # Convert to float and validate range
                value = float(alert[field])
                
                # Range validation
                if field in ["latitude"] and not (-90 <= value <= 90):
                    return False, f"Latitude must be between -90 and 90, got {value}"
                elif field in ["longitude"] and not (-180 <= value <= 180):
                    return False, f"Longitude must be between -180 and 180, got {value}"
                elif field in ["score", "confidence"] and not (0 <= value <= 1):
                    return False, f"Field {field} must be between 0 and 1, got {value}"
                elif field in ["severity"] and not (0 <= value <= 10):
                    return False, f"Severity must be between 0 and 10, got {value}"
                
                # Update with validated float value
                alert[field] = value
                
            except (ValueError, TypeError):
                return False, f"Field {field} must be numeric, got {alert[field]}"
    
    # Validate array fields
    array_fields = ["categories", "tags", "sources", "domains"]
    for field in array_fields:
        if field in alert:
            if alert[field] is None:
                alert[field] = []
            elif not isinstance(alert[field], list):
                try:
                    # Try to convert string to list
                    if isinstance(alert[field], str):
                        alert[field] = [alert[field]]
                    else:
                        alert[field] = list(alert[field])
                except Exception:
                    return False, f"Field {field} must be array or convertible to array"
            
            # Validate array contents are strings
            try:
                alert[field] = [str(item) for item in alert[field] if item is not None]
            except Exception:
                return False, f"Items in {field} must be string-convertible"
    
    # Validate URL fields
    url_fields = ["link", "url", "source_url"]
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    for field in url_fields:
        if field in alert and alert[field] is not None:
            if not isinstance(alert[field], str):
                try:
                    alert[field] = str(alert[field])
                except Exception:
                    return False, f"Field {field} must be string URL"
            
            # Basic URL validation
            if alert[field] and not url_pattern.match(alert[field]):
                logger.warning("invalid_url_detected", field=field, url=alert[field])
                # Don't fail validation, just log warning
    
    return True, ""

def validate_alert_batch(alerts: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Validate a batch of alerts, returning valid alerts and error list.
    
    Args:
        alerts: List of alert dictionaries
        
    Returns:
        Tuple of (valid_alerts: List[Dict], error_messages: List[str])
    """
    
    if not isinstance(alerts, list):
        return [], [f"Alerts must be list, got {type(alerts)}"]
    
    valid_alerts = []
    errors = []
    
    for i, alert in enumerate(alerts):
        is_valid, error = validate_alert(alert)
        if is_valid:
            valid_alerts.append(alert)
        else:
            errors.append(f"Alert {i} ({alert.get('uuid', 'no-uuid')}): {error}")
    
    logger.info("batch_validation_completed", 
               total_alerts=len(alerts),
               valid_alerts=len(valid_alerts),
               invalid_alerts=len(errors))
    
    return valid_alerts, errors

def validate_coordinates(lat: Union[float, str, None], lon: Union[float, str, None]) -> Tuple[bool, Optional[float], Optional[float]]:
    """
    Validate and normalize latitude/longitude coordinates.
    
    Args:
        lat: Latitude value
        lon: Longitude value
        
    Returns:
        Tuple of (is_valid: bool, normalized_lat: float|None, normalized_lon: float|None)
    """
    
    try:
        if lat is None or lon is None:
            return True, None, None
        
        # Convert to float
        lat_float = float(lat)
        lon_float = float(lon)
        
        # Validate ranges
        if not (-90 <= lat_float <= 90):
            return False, None, None
        if not (-180 <= lon_float <= 180):
            return False, None, None
        
        return True, lat_float, lon_float
        
    except (ValueError, TypeError):
        return False, None, None

def sanitize_text_content(text: str, max_length: int = 5000) -> str:
    """
    Sanitize text content for safe processing.
    
    Args:
        text: Raw text content
        max_length: Maximum allowed length
        
    Returns:
        Sanitized text content
    """
    
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove potentially problematic characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]', '', text)
    
    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length]
        logger.warning("text_truncated", original_length=len(text), max_length=max_length)
    
    return text

def validate_enrichment_data(enriched_alert: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate enriched alert data before database storage.
    
    Args:
        enriched_alert: Alert after threat engine processing
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    
    # First run basic alert validation
    is_valid, error = validate_alert(enriched_alert)
    if not is_valid:
        return False, error
    
    # Additional validation for enriched fields
    enriched_fields = {
        "gpt_summary": str,
        "location_confidence": float,
        "risk_score": float,
        "threat_level": str,
        "processed_at": (str, datetime)
    }
    
    for field, expected_type in enriched_fields.items():
        if field in enriched_alert and enriched_alert[field] is not None:
            if not isinstance(enriched_alert[field], expected_type):
                try:
                    # Try type conversion
                    if expected_type == str:
                        enriched_alert[field] = str(enriched_alert[field])
                    elif expected_type == float:
                        enriched_alert[field] = float(enriched_alert[field])
                except Exception:
                    return False, f"Field {field} must be {expected_type}, got {type(enriched_alert[field])}"
    
    return True, ""

# Export validation functions
__all__ = [
    "validate_alert",
    "validate_alert_batch", 
    "validate_coordinates",
    "sanitize_text_content",
    "validate_enrichment_data"
]
