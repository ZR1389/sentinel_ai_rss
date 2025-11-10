# config.py – Centralized configuration with validation
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Set
from urllib.parse import urlparse

@dataclass(frozen=True)
class RSSConfig:
    """Immutable configuration for RSS processor."""
    
    # Fetching
    timeout_sec: float = float(os.getenv("RSS_TIMEOUT_SEC", "20"))
    max_concurrency: int = int(os.getenv("RSS_CONCURRENCY", "16"))
    batch_limit: int = int(os.getenv("RSS_BATCH_LIMIT", "400"))
    freshness_days: int = int(os.getenv("RSS_FRESHNESS_DAYS", "3"))
    
    # Host throttling (NOT backoff)
    host_rate_per_sec: float = float(os.getenv("RSS_HOST_RATE_PER_SEC", "0.5"))
    host_burst: int = int(os.getenv("RSS_HOST_BURST", "2"))
    host_throttle_enabled: bool = os.getenv("HOST_THROTTLE_ENABLED", "true").lower() in ("1", "true", "yes", "y")
    
    # Fulltext extraction
    use_fulltext: bool = os.getenv("RSS_USE_FULLTEXT", "true").lower() in ("1", "true", "yes", "y")
    fulltext_timeout: float = float(os.getenv("RSS_FULLTEXT_TIMEOUT_SEC", "12"))
    fulltext_max_bytes: int = int(os.getenv("RSS_FULLTEXT_MAX_BYTES", "800000"))
    fulltext_max_chars: int = int(os.getenv("RSS_FULLTEXT_MAX_CHARS", "20000"))
    fulltext_concurrency: int = int(os.getenv("RSS_FULLTEXT_CONCURRENCY", "8"))
    
    # Keyword matching
    filter_strict: bool = True
    min_text_length: int = int(os.getenv("RSS_MIN_TEXT_LENGTH", "100"))
    enable_cooccurrence: bool = os.getenv("RSS_ENABLE_COOCCURRENCE", "true").lower() in ("1", "true", "yes", "y")
    cooc_window_tokens: int = int(os.getenv("RSS_COOC_WINDOW_TOKENS", "12"))  # Aligned with risk_shared
    
    # Location extraction
    location_batch_threshold: int = int(os.getenv("MOONSHOT_LOCATION_BATCH_THRESHOLD", "10"))
    geocode_enabled: bool = os.getenv("CITYUTILS_ENABLE_GEOCODE", "true").lower() in ("1", "true", "yes", "y")
    geocode_cache_ttl_days: int = int(os.getenv("GEOCODE_CACHE_TTL_DAYS", "180"))
    countries_geojson_path: str = os.getenv("COUNTRIES_GEOJSON_PATH", "")
    
    # Database
    write_to_db: bool = os.getenv("RSS_WRITE_TO_DB", "true").lower() in ("1", "true", "yes", "y")
    fail_closed: bool = os.getenv("RSS_FAIL_CLOSED", "true").lower() in ("1", "true", "yes", "y")
    database_url: str = os.getenv("DATABASE_URL", "")
    
    # Keywords
    keywords_source: str = os.getenv("KEYWORDS_SOURCE", "merge").lower()
    threat_keywords_path: str = os.getenv("THREAT_KEYWORDS_PATH", "threat_keywords.json")
    
    # Circuit breaker
    cb_failure_threshold: int = int(os.getenv("MOONSHOT_CB_FAILURES", "5"))
    cb_recovery_timeout_sec: float = float(os.getenv("MOONSHOT_CB_TIMEOUT_SEC", "60"))
    cb_half_open_max_calls: int = int(os.getenv("MOONSHOT_CB_HALF_OPEN_MAX", "3"))
    cb_request_volume_threshold: int = int(os.getenv("MOONSHOT_CB_REQUEST_VOLUME", "3"))
    
    @property
    def validated_database_url(self) -> str:
        """Validate database URL is provided when writes are enabled."""
        if self.write_to_db and not self.database_url:
            raise ValueError("DATABASE_URL must be set when RSS_WRITE_TO_DB=true")
        return self.database_url
    
    def __post_init__(self):
        """Validate configuration."""
        if self.fail_closed and not self.write_to_db:
            raise ValueError("RSS_FAIL_CLOSED requires RSS_WRITE_TO_DB=true")
        if self.cooc_window_tokens < 1:
            raise ValueError("RSS_COOC_WINDOW_TOKENS must be >= 1")
        if self.location_batch_threshold < 1:
            raise ValueError("MOONSHOT_LOCATION_BATCH_THRESHOLD must be >= 1")

# Global config instance
CONFIG = RSSConfig()