# config.py – Centralized configuration with validation
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Set, Optional
from urllib.parse import urlparse


def _getenv_bool(key: str, default: bool = False) -> bool:
    """Helper to parse boolean environment variables consistently."""
    value = os.getenv(key, str(default)).lower()
    return value in ("1", "true", "yes", "y", "on")


def _getenv_int(key: str, default: int) -> int:
    """Helper to parse integer environment variables with validation."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        raise ValueError(f"Invalid integer value for {key}: {os.getenv(key)}")


def _getenv_float(key: str, default: float) -> float:
    """Helper to parse float environment variables with validation."""
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        raise ValueError(f"Invalid float value for {key}: {os.getenv(key)}")


@dataclass(frozen=True)
class DatabaseConfig:
    """Database configuration."""
    url: str = os.getenv("DATABASE_URL", "")
    pool_min_size: int = _getenv_int("DB_POOL_MIN_SIZE", 1)
    pool_max_size: int = _getenv_int("DB_POOL_MAX_SIZE", 20)
    
    @property
    def is_configured(self) -> bool:
        return bool(self.url)


@dataclass(frozen=True)
class LLMConfig:
    """LLM provider configuration."""
    # API Keys
    xai_api_key: str = os.getenv("XAI_API_KEY", "")
    xai_temperature: float = _getenv_float("XAI_TEMPERATURE", 0.2)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    moonshot_api_key: str = os.getenv("MOONSHOT_API_KEY", "")
    # Models
    xai_model: str = os.getenv("XAI_MODEL", "grok-3-mini")
    moonshot_model: str = os.getenv("MOONSHOT_MODEL", "moonshot-v1-128k")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    # Timeouts
    deepseek_timeout: float = _getenv_float("DEEPSEEK_TIMEOUT", 10)
    grok_timeout: float = _getenv_float("GROK_TIMEOUT", 15)
    openai_timeout: float = _getenv_float("OPENAI_TIMEOUT", 20)
    moonshot_timeout: float = _getenv_float("MOONSHOT_TIMEOUT", 12)
    chat_timeout: float = _getenv_float("CHAT_TIMEOUT", 60)
    llm_timeout: float = _getenv_float("LLM_TIMEOUT", 30)
    
    # Temperature
    grok_temperature: float = _getenv_float("GROK_TEMPERATURE", 0.3)
    advisor_temperature: float = _getenv_float("ADVISOR_TEMPERATURE", 0.2)
    openai_temperature: float = _getenv_float("OPENAI_TEMPERATURE", 0.4)
    
    # Provider hierarchy
    primary_enrichment: str = os.getenv("LLM_PRIMARY_ENRICHMENT", "grok")
    secondary_verification: str = os.getenv("LLM_SECONDARY_VERIFICATION", "openai")
    tertiary_fallback: str = os.getenv("LLM_TERTIARY_FALLBACK", "moonshot")
    critical_validation: str = os.getenv("LLM_CRITICAL_VALIDATION", "deepseek")


@dataclass(frozen=True)
class EmailConfig:
    """Email configuration."""
    brevo_api_key: str = os.getenv("BREVO_API_KEY", "")
    brevo_sender_email: str = os.getenv("BREVO_SENDER_EMAIL", "")
    brevo_sender_name: str = os.getenv("BREVO_SENDER_NAME", "")
    newsletter_list_id: int = _getenv_int("NEWSLETTER_LIST_ID", 3)
    
    verify_from_email: str = (
        os.getenv("VERIFY_FROM_EMAIL") or 
        os.getenv("BREVO_SENDER_EMAIL") or 
        os.getenv("SENDER_EMAIL") or 
        ""
    ).strip()
    
    site_name: str = (
        os.getenv("SITE_NAME") or 
        os.getenv("BREVO_SENDER_NAME") or 
        "Zika Risk / Sentinel AI"
    ).strip()
    
    # Verification limits
    code_ttl_min: int = _getenv_int("VERIFY_CODE_TTL_MIN", 20)
    ip_window_min: int = _getenv_int("VERIFY_IP_WINDOW_MIN", 10)
    ip_max_requests: int = _getenv_int("VERIFY_IP_MAX_REQUESTS", 6)
    
    # SMTP settings
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = _getenv_int("SMTP_PORT", 587)
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_pass: str = os.getenv("SMTP_PASS", "")
    smtp_tls: bool = _getenv_bool("SMTP_TLS", True)
    email_from: str = os.getenv("EMAIL_FROM", "")
    push_enabled: bool = _getenv_bool("EMAIL_PUSH_ENABLED")


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram configuration."""
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    bot_username: str = os.getenv("TELEGRAM_BOT_USERNAME", "").lstrip("@")
    api_id: str = os.getenv("TELEGRAM_API_ID", "")
    api_hash: str = os.getenv("TELEGRAM_API_HASH", "")
    session: str = os.getenv("TELEGRAM_SESSION", "sentinel")
    
    push_enabled: bool = _getenv_bool("TELEGRAM_PUSH_ENABLED")
    enabled: bool = _getenv_bool("TELEGRAM_ENABLED")
    
    max_msg_age_days: int = _getenv_int("TELEGRAM_MAX_MSG_AGE_DAYS", 7)
    batch_limit: int = _getenv_int("TELEGRAM_BATCH_LIMIT", 300)
    session: str = os.getenv("TELEGRAM_SESSION", "sentinel")


@dataclass(frozen=True)
class SecurityConfig:
    """Security and authentication configuration."""
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    jwt_algorithm: str = os.getenv("JWT_ALG", "HS256")
    jwt_exp_minutes: int = _getenv_int("JWT_EXP_MINUTES", 60)
    jwt_refresh_exp_days: int = _getenv_int("REFRESH_EXP_DAYS", 30)
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "")
    
    # Rate limiting
    chat_rate: str = os.getenv("CHAT_RATE", "10 per minute;200 per day")
    search_rate: str = os.getenv("SEARCH_RATE", "20 per minute;500 per hour")
    batch_enrich_rate: str = os.getenv("BATCH_ENRICH_RATE", "5 per minute;100 per hour")
    chat_query_max_chars: int = _getenv_int("CHAT_QUERY_MAX_CHARS", 5000)
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    security_log_level: str = os.getenv("SECURITY_LOG_LEVEL", "WARNING")
    enable_security_events: bool = _getenv_bool("ENABLE_SECURITY_EVENTS", True)
    structured_logging: bool = _getenv_bool("STRUCTURED_LOGGING")


@dataclass(frozen=True)
class WebPushConfig:
    """Web push notification configuration."""
    vapid_public_key: str = os.getenv("VAPID_PUBLIC_KEY", "")
    vapid_private_key: str = os.getenv("VAPID_PRIVATE_KEY", "")
    vapid_email: str = os.getenv("VAPID_EMAIL", "")
    push_enabled: bool = _getenv_bool("PUSH_ENABLED")


@dataclass(frozen=True)
class ApplicationConfig:
    """Main application configuration."""
    env: str = os.getenv("ENV", "development")
    port: int = _getenv_int("PORT", 8080)
    allowed_origins: str = os.getenv("ALLOWED_ORIGINS", "https://zikarisk.com,https://app.zikarisk.com")
    default_plan: str = os.getenv("DEFAULT_PLAN", "FREE")
    paid_plans: str = os.getenv("PAID_PLANS", "PRO,ENTERPRISE")
    
    # Cache and monitoring
    redis_url: str = os.getenv("REDIS_URL", "")
    cache_ttl_seconds: int = _getenv_int("CACHE_TTL_SECONDS", 3600)
    metrics_enabled: bool = _getenv_bool("METRICS_ENABLED", True)
    performance_monitoring: bool = _getenv_bool("PERFORMANCE_MONITORING", True)
    
    # Data retention
    alert_retention_days: int = _getenv_int("ALERT_RETENTION_DAYS", 90)
    
    # Embedding quota
    embedding_quota_daily: int = _getenv_int("EMBEDDING_QUOTA_DAILY", 10000)
    embedding_requests_daily: int = _getenv_int("EMBEDDING_REQUESTS_DAILY", 5000)


@dataclass(frozen=True)
class RSSConfig:
    """Immutable configuration for RSS processor."""
    
    # Fetching - Remove fallbacks, get from config
    timeout_sec: float = _getenv_float("RSS_TIMEOUT_SEC", 20)
    max_concurrency: int = _getenv_int("RSS_CONCURRENCY", 16)
    batch_limit: int = _getenv_int("RSS_BATCH_LIMIT", 400)
    freshness_days: int = _getenv_int("RSS_FRESHNESS_DAYS", 3)
    
    # Host throttling (NOT backoff)
    host_rate_per_sec: float = _getenv_float("RSS_HOST_RATE_PER_SEC", 0.5)
    host_burst: int = _getenv_int("RSS_HOST_BURST", 2)
    host_throttle_enabled: bool = _getenv_bool("HOST_THROTTLE_ENABLED", True)
    
    # Fulltext extraction
    use_fulltext: bool = _getenv_bool("RSS_USE_FULLTEXT", True)
    fulltext_timeout: float = _getenv_float("RSS_FULLTEXT_TIMEOUT_SEC", 12)
    fulltext_max_bytes: int = _getenv_int("RSS_FULLTEXT_MAX_BYTES", 800000)
    fulltext_max_chars: int = _getenv_int("RSS_FULLTEXT_MAX_CHARS", 20000)
    fulltext_concurrency: int = _getenv_int("RSS_FULLTEXT_CONCURRENCY", 8)
    
    # Keyword matching
    filter_strict: bool = True  # Always strict, no fallback
    min_text_length: int = _getenv_int("RSS_MIN_TEXT_LENGTH", 100)
    enable_cooccurrence: bool = _getenv_bool("RSS_ENABLE_COOCCURRENCE", True)
    cooc_window_tokens: int = _getenv_int("RSS_COOC_WINDOW_TOKENS", 12)
    
    # Location extraction
    location_batch_threshold: int = _getenv_int("MOONSHOT_LOCATION_BATCH_THRESHOLD", 10)
    geocode_enabled: bool = _getenv_bool("CITYUTILS_ENABLE_GEOCODE", True)
    geocode_cache_ttl_days: int = _getenv_int("GEOCODE_CACHE_TTL_DAYS", 180)
    countries_geojson_path: str = os.getenv("COUNTRIES_GEOJSON_PATH", "")
    
    # Database
    write_to_db: bool = _getenv_bool("RSS_WRITE_TO_DB", True)
    fail_closed: bool = _getenv_bool("RSS_FAIL_CLOSED", True)
    
    # Keywords
    keywords_source: str = os.getenv("KEYWORDS_SOURCE", "merge").lower()
    threat_keywords_path: str = os.getenv("THREAT_KEYWORDS_PATH", "threat_keywords.json")
    
    # Circuit breaker
    cb_failure_threshold: int = _getenv_int("MOONSHOT_CB_FAILURES", 5)
    cb_recovery_timeout_sec: float = _getenv_float("MOONSHOT_CB_TIMEOUT_SEC", 60)
    cb_half_open_max_calls: int = _getenv_int("MOONSHOT_CB_HALF_OPEN_MAX", 3)
    cb_request_volume_threshold: int = _getenv_int("MOONSHOT_CB_REQUEST_VOLUME", 3)
    
    def __post_init__(self):
        """Validate configuration."""
        if self.fail_closed and not self.write_to_db:
            raise ValueError("RSS_FAIL_CLOSED requires RSS_WRITE_TO_DB=true")
        if self.cooc_window_tokens < 1:
            raise ValueError("RSS_COOC_WINDOW_TOKENS must be >= 1")
        if self.location_batch_threshold < 1:
            raise ValueError("MOONSHOT_LOCATION_BATCH_THRESHOLD must be >= 1")


@dataclass(frozen=True)
class BatchProcessingConfig:
    """Optimized batch processing configuration."""
    # Buffer management
    max_buffer_size: int = _getenv_int("BATCH_MAX_BUFFER_SIZE", 1000)
    max_buffer_age_seconds: int = _getenv_int("BATCH_MAX_BUFFER_AGE_SEC", 3600)  # 1 hour
    max_result_age_seconds: int = _getenv_int("BATCH_MAX_RESULT_AGE_SEC", 7200)  # 2 hours
    
    # Flush triggers - optimized for performance
    size_threshold: int = _getenv_int("BATCH_SIZE_THRESHOLD", 25)  # Optimal for LLM APIs
    time_threshold_seconds: float = _getenv_float("BATCH_TIME_THRESHOLD_SEC", 300.0)  # 5 minutes
    
    # Performance optimization
    enable_adaptive_sizing: bool = _getenv_bool("BATCH_ENABLE_ADAPTIVE_SIZING", True)
    enable_priority_flushing: bool = _getenv_bool("BATCH_ENABLE_PRIORITY_FLUSHING", True)
    enable_performance_monitoring: bool = _getenv_bool("BATCH_ENABLE_PERFORMANCE_MONITORING", True)
    enable_timer_flush: bool = _getenv_bool("BATCH_ENABLE_TIMER_FLUSH", True)
    
    # Optimized thresholds
    optimal_batch_size: int = _getenv_int("BATCH_OPTIMAL_SIZE", 25)
    min_batch_size: int = _getenv_int("BATCH_MIN_SIZE", 5)
    max_batch_size: int = _getenv_int("BATCH_MAX_SIZE", 50)
    
    # Timeout optimization
    fast_flush_timeout_sec: float = _getenv_float("BATCH_FAST_FLUSH_TIMEOUT_SEC", 120.0)  # 2 minutes
    emergency_timeout_sec: float = _getenv_float("BATCH_EMERGENCY_TIMEOUT_SEC", 60.0)  # 1 minute
    
    # Performance targets
    performance_target_ms: float = _getenv_float("BATCH_PERFORMANCE_TARGET_MS", 2000.0)  # 2s target
    throughput_target_eps: float = _getenv_float("BATCH_THROUGHPUT_TARGET_EPS", 10.0)  # 10 entries/sec
    
    # Memory management
    memory_pressure_threshold: float = _getenv_float("BATCH_MEMORY_PRESSURE_THRESHOLD", 0.85)  # 85%
    aggressive_flush_threshold: float = _getenv_float("BATCH_AGGRESSIVE_FLUSH_THRESHOLD", 0.95)  # 95%
    
    def __post_init__(self):
        """Validate batch processing configuration."""
        if self.max_buffer_size < 1:
            raise ValueError("BATCH_MAX_BUFFER_SIZE must be >= 1")
        if self.size_threshold < 1:
            raise ValueError("BATCH_SIZE_THRESHOLD must be >= 1")
        if self.min_batch_size < 1:
            raise ValueError("BATCH_MIN_SIZE must be >= 1")
        if self.min_batch_size > self.max_batch_size:
            raise ValueError("BATCH_MIN_SIZE must be <= BATCH_MAX_SIZE")
        if self.size_threshold > self.max_buffer_size:
            raise ValueError("BATCH_SIZE_THRESHOLD must be <= BATCH_MAX_BUFFER_SIZE")
        if not (0.0 < self.memory_pressure_threshold < 1.0):
            raise ValueError("BATCH_MEMORY_PRESSURE_THRESHOLD must be between 0.0 and 1.0")
        if not (0.0 < self.aggressive_flush_threshold <= 1.0):
            raise ValueError("BATCH_AGGRESSIVE_FLUSH_THRESHOLD must be between 0.0 and 1.0")
        if self.memory_pressure_threshold >= self.aggressive_flush_threshold:
            raise ValueError("BATCH_MEMORY_PRESSURE_THRESHOLD must be < BATCH_AGGRESSIVE_FLUSH_THRESHOLD")


@dataclass(frozen=True)
class Config:
    """Master configuration object."""
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    webpush: WebPushConfig = field(default_factory=WebPushConfig)
    app: ApplicationConfig = field(default_factory=ApplicationConfig)
    rss: RSSConfig = field(default_factory=RSSConfig)
    batch_processing: BatchProcessingConfig = field(default_factory=BatchProcessingConfig)
    
    def validate(self):
        """Validate the complete configuration."""
        if self.rss.write_to_db and not self.database.is_configured:
            raise ValueError("DATABASE_URL must be set when RSS_WRITE_TO_DB=true")
        
        # Validate RSS config
        self.rss.__post_init__()
        
        # Validate batch processing config
        self.batch_processing.__post_init__()


# Global config instance - no fallbacks, everything centralized
CONFIG = Config()

# Validate configuration on import
try:
    CONFIG.validate()
except Exception as e:
    import sys
    print(f"Configuration validation failed: {e}")
    print("Please check your environment variables.")
    # Don't exit during import, let the application handle it
    pass