import os
import time
import threading
import logging
from functools import wraps
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger("llm_rate_limiter")

class TokenBucket:
    def __init__(self, tokens_per_minute: int, name: str):
        self.capacity = tokens_per_minute
        self.tokens = tokens_per_minute
        self.last_refill = time.time()
        self.lock = threading.Lock()
        self.name = name
        self.metrics = deque(maxlen=1000)  # Track last 1000 requests
    
    def consume(self, tokens: int = 1) -> bool:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            # Refill tokens based on time passed (per minute rate)
            new_tokens = elapsed * (self.capacity / 60.0)
            self.tokens = min(self.capacity, self.tokens + new_tokens)
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                self.metrics.append({
                    "timestamp": datetime.utcnow(),
                    "tokens": tokens,
                    "remaining": self.tokens
                })
                return True
            return False
    
    def get_metrics(self):
        """Return rate limit stats for monitoring"""
        now = datetime.utcnow()
        last_minute = [m for m in self.metrics if now - m["timestamp"] < timedelta(minutes=1)]
        return {
            "requests_last_minute": len(last_minute),
            "tokens_consumed": sum(m["tokens"] for m in last_minute),
            "remaining_tokens": self.tokens,
            "capacity": self.capacity,
            "service": self.name
        }

# Instantiate limiters per LLM service
openai_limiter = TokenBucket(int(os.getenv("OPENAI_TPM_LIMIT", "3000")), "openai")
xai_limiter = TokenBucket(int(os.getenv("XAI_TPM_LIMIT", "1500")), "xai")
deepseek_limiter = TokenBucket(int(os.getenv("DEEPSEEK_TPM_LIMIT", "5000")), "deepseek")
moonshot_limiter = TokenBucket(int(os.getenv("MOONSHOT_TPM_LIMIT", "1000")), "moonshot")

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300, name: str = "llm"):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half_open
        self.lock = threading.Lock()
    
    def call(self, func, *args, **kwargs):
        with self.lock:
            if self.state == "open":
                if time.time() - self.last_failure_time < self.recovery_timeout:
                    raise Exception(f"Circuit breaker open for {self.name}")
                else:
                    self.state = "half_open"
                    logger.info(f"[CircuitBreaker] {self.name} entering half_open state")
        
        try:
            result = func(*args, **kwargs)
            # Success - reset circuit
            with self.lock:
                self.failure_count = 0
                self.state = "closed"
                logger.debug(f"[CircuitBreaker] {self.name} success, circuit closed")
            return result
        except Exception as e:
            with self.lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.failure_threshold:
                    self.state = "open"
                    logger.error(f"[CircuitBreaker] {self.name} circuit OPEN after {self.failure_count} failures")
            raise

# Create circuit breakers
openai_circuit = CircuitBreaker(name="openai")
xai_circuit = CircuitBreaker(name="xai")
deepseek_circuit = CircuitBreaker(name="deepseek")
moonshot_circuit = CircuitBreaker(name="moonshot")

def rate_limited(service: str):
    """Decorator for rate limiting"""
    limiter = {
        "openai": openai_limiter,
        "xai": xai_limiter,
        "deepseek": deepseek_limiter,
        "moonshot": moonshot_limiter
    }[service]
    
    circuit = {
        "openai": openai_circuit,
        "xai": xai_circuit,
        "deepseek": deepseek_circuit,
        "moonshot": moonshot_circuit
    }[service]
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract timeout from kwargs or use default
            timeout = kwargs.get('timeout', 15)
            
            # Wait for token availability with timeout
            wait_start = time.time()
            while not limiter.consume():
                if time.time() - wait_start > timeout:
                    raise TimeoutError(f"Rate limit wait exceeded {timeout}s for {service}")
                time.sleep(0.1)  # Poll every 100ms
            
            # Call through circuit breaker
            return circuit.call(func, *args, **kwargs)
        return wrapper
    return decorator

def get_rate_limiter_stats():
    """Get comprehensive rate limiting stats for monitoring"""
    return {
        "openai": openai_limiter.get_metrics(),
        "xai": xai_limiter.get_metrics(),
        "deepseek": deepseek_limiter.get_metrics(),
        "moonshot": moonshot_limiter.get_metrics()
    }

def get_all_rate_limit_stats():
    """Alias for get_rate_limiter_stats for consistency"""
    return get_rate_limiter_stats()

def get_circuit_breaker_stats():
    """Get circuit breaker status for monitoring"""
    return {
        "openai": {
            "state": openai_circuit.state,
            "failure_count": openai_circuit.failure_count,
            "last_failure": openai_circuit.last_failure_time,
            "service": "openai"
        },
        "xai": {
            "state": xai_circuit.state,
            "failure_count": xai_circuit.failure_count,
            "last_failure": xai_circuit.last_failure_time,
            "service": "xai"
        },
        "deepseek": {
            "state": deepseek_circuit.state,
            "failure_count": deepseek_circuit.failure_count,
            "last_failure": deepseek_circuit.last_failure_time,
            "service": "deepseek"
        },
        "moonshot": {
            "state": moonshot_circuit.state,
            "failure_count": moonshot_circuit.failure_count,
            "last_failure": moonshot_circuit.last_failure_time,
            "service": "moonshot"
        }
    }

def get_all_circuit_breaker_stats():
    """Alias for get_circuit_breaker_stats for consistency"""
    return get_circuit_breaker_stats()

def reset_circuit_breaker(service: str):
    """Reset circuit breaker for a specific service (admin function)"""
    circuit = {
        "openai": openai_circuit,
        "xai": xai_circuit,
        "deepseek": deepseek_circuit,
        "moonshot": moonshot_circuit
    }.get(service)
    
    if circuit:
        with circuit.lock:
            circuit.failure_count = 0
            circuit.state = "closed"
            circuit.last_failure_time = None
            logger.info(f"[CircuitBreaker] {service} circuit manually reset")
        return True
    return False

def get_health_status():
    """Get overall system health status for monitoring dashboards"""
    rate_stats = get_all_rate_limit_stats()
    circuit_stats = get_all_circuit_breaker_stats()
    
    overall_status = "healthy"
    issues = []
    
    for service in ["openai", "xai", "deepseek", "moonshot"]:
        # Check rate limiting health
        remaining_ratio = rate_stats[service]["remaining_tokens"] / rate_stats[service]["capacity"]
        if remaining_ratio < 0.1:  # Less than 10% tokens remaining
            issues.append(f"{service}_rate_limit_low")
        
        # Check circuit breaker health
        if circuit_stats[service]["state"] == "open":
            issues.append(f"{service}_circuit_breaker_open")
            overall_status = "degraded"
        elif circuit_stats[service]["failure_count"] > 2:
            issues.append(f"{service}_elevated_errors")
    
    if issues:
        overall_status = "degraded" if overall_status != "degraded" else "degraded"
    
    return {
        "status": overall_status,
        "issues": issues,
        "timestamp": time.time(),
        "services_available": [s for s in ["openai", "xai", "deepseek", "moonshot"] 
                              if circuit_stats[s]["state"] != "open"]
    }
