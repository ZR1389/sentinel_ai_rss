# logging_config.py - Structured logging for production observability
import structlog
import logging
import os
import sys
from typing import Optional

def setup_logging(service_name: Optional[str] = None) -> None:
    """
    Configure structured logging for production
    
    Args:
        service_name: Name of the service (e.g., "sentinel-api", "retention-worker")
    """
    
    # Clear existing handlers to avoid duplicates
    logging.root.handlers.clear()
    
    # Base processors for all environments
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    
    # Add service context if provided
    if service_name:
        processors.insert(0, structlog.processors.add_log_level)
        processors.insert(0, lambda logger, method_name, event_dict: 
                         dict(event_dict, service=service_name))
    
    # Choose output format based on environment
    is_production = os.getenv("RAILWAY_ENVIRONMENT_NAME") is not None
    use_json = os.getenv("STRUCTURED_LOGGING", "true" if is_production else "false").lower() == "true"
    
    if use_json:
        # JSON logging for production (Datadog, New Relic, etc.)
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Human-readable logging for development
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level, logging.INFO),
        handlers=[logging.StreamHandler()],
        force=True  # Override existing configuration
    )
    
    # Reduce noise from verbose libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance
    
    Args:
        name: Logger name (usually module name)
        
    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)

# Performance and metrics helpers
class MetricsLogger:
    """Helper class for consistent metrics logging"""
    
    def __init__(self, logger: structlog.stdlib.BoundLogger):
        self.logger = logger
    
    def alert_processed(self, alert_uuid: str, score: float, duration_ms: int, 
                       cache_hit: bool = False, **kwargs):
        """Log alert processing metrics"""
        self.logger.info(
            "alert_processed",
            alert_uuid=alert_uuid,
            score=score,
            duration_ms=duration_ms,
            cache_hit=cache_hit,
            **kwargs
        )
    
    def alert_enriched(self, alert_uuid: str, confidence: float, duration_ms: int,
                      location_confidence: float = None, **kwargs):
        """Log alert enrichment metrics"""
        self.logger.info(
            "alert_enriched",
            alert_uuid=alert_uuid,
            confidence=confidence,
            duration_ms=duration_ms,
            location_confidence=location_confidence,
            **kwargs
        )
    
    def database_operation(self, operation: str, table: str, duration_ms: int,
                          rows_affected: int = None, **kwargs):
        """Log database operation metrics"""
        self.logger.info(
            "database_operation",
            operation=operation,
            table=table,
            duration_ms=duration_ms,
            rows_affected=rows_affected,
            **kwargs
        )
    
    def api_request(self, endpoint: str, method: str, status_code: int,
                   duration_ms: int, user_email: str = None, **kwargs):
        """Log API request metrics"""
        self.logger.info(
            "api_request",
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            duration_ms=duration_ms,
            user_email=user_email,
            **kwargs
        )
    
    def llm_request(self, provider: str, model: str, duration_ms: int,
                   prompt_tokens: int = None, completion_tokens: int = None,
                   cache_hit: bool = False, **kwargs):
        """Log LLM request metrics"""
        self.logger.info(
            "llm_request",
            provider=provider,
            model=model,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit=cache_hit,
            **kwargs
        )

def get_metrics_logger(name: str) -> MetricsLogger:
    """Get a metrics logger instance"""
    logger = get_logger(name)
    return MetricsLogger(logger)

# Initialize logging on import for backwards compatibility
setup_logging("sentinel-api")
