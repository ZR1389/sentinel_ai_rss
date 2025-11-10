# metrics.py – Production metrics
from __future__ import annotations
import time
import asyncio
from collections import defaultdict
from typing import Dict, Callable, Any
from functools import wraps

class MetricsCollector:
    def __init__(self):
        self.counters: Dict[str, int] = defaultdict(int)
        self.timers: Dict[str, list] = defaultdict(list)
        self.gauges: Dict[str, float] = {}
    
    def increment(self, name: str, value: int = 1):
        self.counters[name] += value
    
    def timing(self, name: str, duration_ms: float):
        self.timers[name].append(duration_ms)
    
    def gauge(self, name: str, value: float):
        self.gauges[name] = value
    
    def timer(self, name: str) -> Callable:
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    self.timing(name, duration_ms)
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    self.timing(name, duration_ms)
            
            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return decorator

# Global metrics instance
METRICS = MetricsCollector()

class RSSProcessorMetrics:
    """RSS Processor specific metrics wrapper"""
    
    def __init__(self):
        self.collector = METRICS
    
    def record_feed_processing_time(self, duration_seconds: float):
        """Record time taken to process feeds"""
        self.collector.timing("rss.feed_processing_time", duration_seconds * 1000)
    
    def record_location_extraction_time(self, duration_seconds: float, method: str = "unknown"):
        """Record time taken for location extraction by method"""
        self.collector.timing(f"rss.location_extraction_time.{method}", duration_seconds * 1000)
    
    def record_batch_processing_time(self, duration_seconds: float, batch_size: int = 0):
        """Record time taken for batch processing"""
        self.collector.timing("rss.batch_processing_time", duration_seconds * 1000)
        if batch_size > 0:
            self.collector.gauge("rss.batch_size", float(batch_size))
    
    def increment_error_count(self, category: str, error_type: str):
        """Increment error counter by category and type"""
        self.collector.increment(f"rss.errors.{category}.{error_type}")
    
    def increment_alert_count(self, count: int):
        """Increment number of alerts processed"""
        self.collector.increment("rss.alerts_processed", count)
    
    def set_batch_size(self, size: int):
        """Set current batch size gauge"""
        self.collector.gauge("rss.current_batch_size", float(size))
    
    def record_database_operation_time(self, duration_seconds: float, operation: str = "unknown"):
        """Record database operation timing"""
        self.collector.timing(f"rss.database.{operation}_time", duration_seconds * 1000)
    
    def record_llm_api_call_time(self, duration_seconds: float, provider: str = "unknown", operation: str = "call"):
        """Record LLM API call timing"""
        self.collector.timing(f"rss.llm.{provider}.{operation}_time", duration_seconds * 1000)
    
    def get_metrics_summary(self) -> dict:
        """Get summary of all collected metrics"""
        return {
            "counters": dict(self.collector.counters),
            "timers": {k: {
                "count": len(v),
                "avg_ms": sum(v) / len(v) if v else 0,
                "min_ms": min(v) if v else 0,
                "max_ms": max(v) if v else 0
            } for k, v in self.collector.timers.items()},
            "gauges": dict(self.collector.gauges)
        }