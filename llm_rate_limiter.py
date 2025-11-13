import os
import time
import threading
import logging
import random
import json
import asyncio
from functools import wraps
from collections import deque, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("llm_rate_limiter")

class RetryErrorType(Enum):
    """Classification of retry-eligible errors"""
    TRANSIENT_NETWORK = "transient_network"
    RATE_LIMIT = "rate_limit" 
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    AUTHENTICATION = "authentication"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"

@dataclass
class RetryMetrics:
    """Tracking metrics for retry operations"""
    total_attempts: int = 0
    successful_retries: int = 0
    failed_retries: int = 0
    total_retry_time: float = 0.0
    error_counts: Dict[str, int] = field(default_factory=dict)
    backoff_times: List[float] = field(default_factory=list)
    last_retry_timestamp: Optional[float] = None

@dataclass
class CircuitBreakerMetrics:
    """Enhanced metrics for circuit breaker monitoring"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    circuit_opens: int = 0
    circuit_closes: int = 0
    time_in_open_state: float = 0.0
    recovery_attempts: int = 0
    last_failure_timestamp: Optional[float] = None
    error_types: Dict[str, int] = field(default_factory=dict)

class TokenBucket:
    """Enhanced token bucket with comprehensive monitoring"""
    def __init__(self, tokens_per_minute: int, name: str):
        self.capacity = tokens_per_minute
        self.tokens = tokens_per_minute
        self.last_refill = time.time()
        self.lock = threading.Lock()
        self.name = name
        self.metrics = deque(maxlen=1000)  # Track last 1000 requests
        
        # Enhanced monitoring
        self.violation_count = 0
        self.total_requests = 0
        self.denied_requests = 0
        self.average_wait_time = 0.0
        self.peak_usage_timestamp = None
        self.peak_usage_rate = 0.0
        
        logger.info(f"[TokenBucket] Initialized {name} with {tokens_per_minute} tokens/minute")
    
    def consume(self, tokens: int = 1) -> bool:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            
            # Refill tokens based on time passed (per minute rate)
            new_tokens = elapsed * (self.capacity / 60.0)
            self.tokens = min(self.capacity, self.tokens + new_tokens)
            self.last_refill = now
            
            # Update monitoring metrics
            self.total_requests += 1
            current_usage_rate = (self.capacity - self.tokens) / self.capacity
            
            if current_usage_rate > self.peak_usage_rate:
                self.peak_usage_rate = current_usage_rate
                self.peak_usage_timestamp = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                self.metrics.append({
                    "timestamp": datetime.utcnow(),
                    "tokens": tokens,
                    "remaining": self.tokens,
                    "usage_rate": current_usage_rate,
                    "success": True
                })
                return True
            else:
                # Rate limit violation
                self.denied_requests += 1
                self.violation_count += 1
                self.metrics.append({
                    "timestamp": datetime.utcnow(),
                    "tokens": tokens,
                    "remaining": self.tokens,
                    "usage_rate": current_usage_rate,
                    "success": False
                })
                logger.warning(f"[TokenBucket] Rate limit violated for {self.name}: "
                             f"requested={tokens}, available={self.tokens:.1f}")
                return False
    
    def get_comprehensive_metrics(self):
        """Return detailed rate limit stats for monitoring"""
        now = datetime.utcnow()
        last_minute = [m for m in self.metrics if now - m["timestamp"] < timedelta(minutes=1)]
        last_hour = [m for m in self.metrics if now - m["timestamp"] < timedelta(hours=1)]
        
        # Calculate statistics
        success_rate = (len([m for m in last_minute if m["success"]]) / len(last_minute)) if last_minute else 1.0
        avg_usage = sum(m["usage_rate"] for m in last_minute) / len(last_minute) if last_minute else 0.0
        
        return {
            "service": self.name,
            "capacity": self.capacity,
            "remaining_tokens": self.tokens,
            "utilization": (self.capacity - self.tokens) / self.capacity,
            "requests_last_minute": len(last_minute),
            "requests_last_hour": len(last_hour),
            "tokens_consumed_minute": sum(m["tokens"] for m in last_minute),
            "success_rate": success_rate,
            "average_usage_rate": avg_usage,
            "total_requests": self.total_requests,
            "denied_requests": self.denied_requests,
            "violation_count": self.violation_count,
            "peak_usage_rate": self.peak_usage_rate,
            "peak_usage_timestamp": self.peak_usage_timestamp,
            "health_status": "healthy" if success_rate > 0.95 else "degraded" if success_rate > 0.8 else "critical"
        }
    
    def get_metrics(self):
        """Backward compatibility method"""
        metrics = self.get_comprehensive_metrics()
        return {
            "requests_last_minute": metrics["requests_last_minute"],
            "tokens_consumed": metrics["tokens_consumed_minute"],
            "remaining_tokens": metrics["remaining_tokens"],
            "capacity": metrics["capacity"],
            "service": metrics["service"]
        }

# Instantiate limiters per LLM service
openai_limiter = TokenBucket(int(os.getenv("OPENAI_TPM_LIMIT", "3000")), "openai")
xai_limiter = TokenBucket(int(os.getenv("XAI_TPM_LIMIT", "1500")), "xai")
deepseek_limiter = TokenBucket(int(os.getenv("DEEPSEEK_TPM_LIMIT", "5000")), "deepseek")
moonshot_limiter = TokenBucket(int(os.getenv("MOONSHOT_TPM_LIMIT", "1000")), "moonshot")

class EnhancedCircuitBreaker:
    """Enhanced circuit breaker with comprehensive monitoring and intelligent recovery"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300, 
                 name: str = "llm", failure_rate_threshold: float = 0.5,
                 request_volume_threshold: int = 10, half_open_max_calls: int = 3):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_rate_threshold = failure_rate_threshold
        self.request_volume_threshold = request_volume_threshold
        self.half_open_max_calls = half_open_max_calls
        self.name = name
        
        # State management
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half_open
        self.lock = threading.Lock()
        
        # Enhanced monitoring
        self.metrics = CircuitBreakerMetrics()
        self.request_history = deque(maxlen=100)  # Last 100 requests
        self.error_patterns = defaultdict(int)
        self.recovery_attempts = 0
        self.state_transitions = deque(maxlen=50)  # Track state changes
        
        logger.info(f"[CircuitBreaker] Initialized {name}: threshold={failure_threshold}, "
                   f"timeout={recovery_timeout}s, failure_rate={failure_rate_threshold}")
    
    def classify_error(self, exception: Exception) -> RetryErrorType:
        """Classify errors to determine retry eligibility"""
        error_message = str(exception).lower()
        
        if "timeout" in error_message or "timed out" in error_message:
            return RetryErrorType.TIMEOUT
        elif "rate limit" in error_message or "429" in error_message:
            return RetryErrorType.RATE_LIMIT
        elif "connection" in error_message or "network" in error_message:
            return RetryErrorType.TRANSIENT_NETWORK
        elif "500" in error_message or "502" in error_message or "503" in error_message:
            return RetryErrorType.SERVER_ERROR
        elif "401" in error_message or "403" in error_message:
            return RetryErrorType.AUTHENTICATION
        elif "400" in error_message or "404" in error_message:
            return RetryErrorType.PERMANENT
        else:
            return RetryErrorType.UNKNOWN
    
    def should_attempt_call(self) -> bool:
        """Check if call should be attempted based on circuit state"""
        with self.lock:
            if self.state == "closed":
                return True
            elif self.state == "open":
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = "half_open"
                    self.recovery_attempts += 1
                    self._record_state_transition("open", "half_open", "timeout_recovery")
                    logger.info(f"[CircuitBreaker] {self.name} transitioning to half_open "
                              f"(attempt #{self.recovery_attempts})")
                    return True
                return False
            elif self.state == "half_open":
                # Allow limited calls in half-open state
                recent_calls = len([r for r in self.request_history 
                                  if time.time() - r["timestamp"] < 60])
                return recent_calls < self.half_open_max_calls
            return False
    
    def _record_state_transition(self, from_state: str, to_state: str, reason: str):
        """Record state transitions for analysis"""
        transition = {
            "timestamp": time.time(),
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason
        }
        self.state_transitions.append(transition)
        logger.info(f"[CircuitBreaker] {self.name} state: {from_state} -> {to_state} ({reason})")
    
    def call(self, func, *args, **kwargs):
        """Execute function through circuit breaker with enhanced monitoring"""
        if not self.should_attempt_call():
            self.metrics.failed_requests += 1
            raise Exception(f"Circuit breaker open for {self.name}")
        
        start_time = time.time()
        request_record = {
            "timestamp": start_time,
            "success": False,
            "error_type": None,
            "duration": 0.0
        }
        
        try:
            # Execute the function
            result = func(*args, **kwargs)
            
            # Success - update metrics and potentially close circuit
            duration = time.time() - start_time
            request_record.update({
                "success": True,
                "duration": duration
            })
            
            with self.lock:
                self.metrics.successful_requests += 1
                self.metrics.total_requests += 1
                
                if self.state == "half_open":
                    # Check if we can close the circuit
                    recent_successes = len([r for r in self.request_history[-self.half_open_max_calls:] 
                                          if r["success"]])
                    if recent_successes >= self.half_open_max_calls:
                        old_state = self.state
                        self.state = "closed"
                        self.failure_count = 0
                        self.metrics.circuit_closes += 1
                        self._record_state_transition(old_state, "closed", "recovery_success")
                elif self.state == "closed":
                    # Reset failure count on success
                    self.failure_count = max(0, self.failure_count - 1)
            
            self.request_history.append(request_record)
            return result
            
        except Exception as e:
            # Failure - update metrics and potentially open circuit
            duration = time.time() - start_time
            error_type = self.classify_error(e)
            
            request_record.update({
                "success": False,
                "error_type": error_type.value,
                "duration": duration,
                "error_message": str(e)[:100]  # Truncate long messages
            })
            
            with self.lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                self.metrics.failed_requests += 1
                self.metrics.total_requests += 1
                self.metrics.last_failure_timestamp = time.time()
                self.metrics.error_types[error_type.value] = self.metrics.error_types.get(error_type.value, 0) + 1
                self.error_patterns[str(e)[:50]] += 1
                
                # Determine if circuit should open
                should_open = False
                
                # Check failure count threshold
                if self.failure_count >= self.failure_threshold:
                    should_open = True
                
                # Check failure rate threshold
                recent_requests = [r for r in self.request_history if time.time() - r["timestamp"] < 300]
                if len(recent_requests) >= self.request_volume_threshold:
                    failure_rate = len([r for r in recent_requests if not r["success"]]) / len(recent_requests)
                    if failure_rate >= self.failure_rate_threshold:
                        should_open = True
                
                if should_open and self.state != "open":
                    old_state = self.state
                    self.state = "open"
                    self.metrics.circuit_opens += 1
                    self._record_state_transition(old_state, "open", 
                                                f"failures={self.failure_count}, rate={failure_rate:.2f}")
            
            self.request_history.append(request_record)
            raise
    
    def get_comprehensive_metrics(self) -> Dict[str, Any]:
        """Get detailed circuit breaker metrics"""
        with self.lock:
            recent_requests = [r for r in self.request_history if time.time() - r["timestamp"] < 300]
            failure_rate = 0.0
            avg_response_time = 0.0
            
            if recent_requests:
                failures = len([r for r in recent_requests if not r["success"]])
                failure_rate = failures / len(recent_requests)
                avg_response_time = sum(r["duration"] for r in recent_requests) / len(recent_requests)
            
            return {
                "service": self.name,
                "state": self.state,
                "failure_count": self.failure_count,
                "last_failure": self.last_failure_time,
                "total_requests": self.metrics.total_requests,
                "successful_requests": self.metrics.successful_requests,
                "failed_requests": self.metrics.failed_requests,
                "circuit_opens": self.metrics.circuit_opens,
                "circuit_closes": self.metrics.circuit_closes,
                "recovery_attempts": self.recovery_attempts,
                "failure_rate": failure_rate,
                "avg_response_time": avg_response_time,
                "error_types": dict(self.metrics.error_types),
                "error_patterns": dict(list(self.error_patterns.items())[:5]),  # Top 5 errors
                "recent_requests": len(recent_requests),
                "health_status": "healthy" if self.state == "closed" and failure_rate < 0.1 
                               else "degraded" if self.state == "half_open" 
                               else "critical",
                "state_transitions": list(self.state_transitions)[-5:],  # Last 5 transitions
            }

# Backward-compatibility alias for older tests/imports
class CircuitBreaker(EnhancedCircuitBreaker):
    pass

# Enhanced circuit breakers with comprehensive monitoring
openai_circuit = EnhancedCircuitBreaker(name="openai", failure_threshold=5, recovery_timeout=300)
xai_circuit = EnhancedCircuitBreaker(name="xai", failure_threshold=3, recovery_timeout=180)
deepseek_circuit = EnhancedCircuitBreaker(name="deepseek", failure_threshold=4, recovery_timeout=240)
moonshot_circuit = EnhancedCircuitBreaker(name="moonshot", failure_threshold=3, recovery_timeout=180)

def classify_error_for_retry(exception: Exception) -> RetryErrorType:
    """Classify errors for retry decision making"""
    error_message = str(exception).lower()
    
    # Network and connectivity issues - usually transient
    if any(keyword in error_message for keyword in [
        "connection", "network", "dns", "socket", "ssl", "tls"
    ]):
        return RetryErrorType.TRANSIENT_NETWORK
    
    # Timeout issues - often transient
    if any(keyword in error_message for keyword in [
        "timeout", "timed out", "read timeout", "connect timeout"
    ]):
        return RetryErrorType.TIMEOUT
    
    # Rate limiting - should retry with backoff
    if any(keyword in error_message for keyword in [
        "rate limit", "429", "quota", "too many requests"
    ]):
        return RetryErrorType.RATE_LIMIT
    
    # Server errors - potentially transient
    if any(keyword in error_message for keyword in [
        "500", "502", "503", "504", "internal server error", "bad gateway", 
        "service unavailable", "gateway timeout"
    ]):
        return RetryErrorType.SERVER_ERROR
    
    # Authentication errors - usually permanent
    if any(keyword in error_message for keyword in [
        "401", "403", "unauthorized", "forbidden", "authentication", "api key"
    ]):
        return RetryErrorType.AUTHENTICATION
    
    # Client errors - usually permanent
    if any(keyword in error_message for keyword in [
        "400", "404", "405", "422", "bad request", "not found", "method not allowed"
    ]):
        return RetryErrorType.PERMANENT
    
    return RetryErrorType.UNKNOWN

def calculate_backoff_delay(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0, 
                           jitter: bool = True, exponential: bool = True) -> float:
    """Calculate intelligent backoff delay with jitter"""
    if exponential:
        delay = base_delay * (2 ** attempt)
    else:
        delay = base_delay * (attempt + 1)  # Linear backoff
    
    # Cap the delay
    delay = min(delay, max_delay)
    
    # Add jitter to prevent thundering herd
    if jitter:
        jitter_range = delay * 0.1  # ±10% jitter
        delay += random.uniform(-jitter_range, jitter_range)
    
    return max(0.1, delay)  # Minimum 100ms delay

def retry_with_backoff(
    func: Callable, 
    max_retries: int = 3, 
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_on: Optional[List[RetryErrorType]] = None,
    timeout: Optional[float] = None,
    context: Optional[str] = None
) -> Any:
    """
    Enhanced retry mechanism with exponential backoff and intelligent error handling.
    
    Args:
        func: Function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for first retry
        max_delay: Maximum delay between retries
        backoff_factor: Exponential backoff multiplier
        jitter: Add randomness to prevent thundering herd
        retry_on: List of error types to retry on (None = retry on transient errors)
        timeout: Total timeout for all attempts
        context: Context string for logging
        
    Returns:
        Function result or raises last exception
    """
    if retry_on is None:
        retry_on = [
            RetryErrorType.TRANSIENT_NETWORK,
            RetryErrorType.TIMEOUT,
            RetryErrorType.SERVER_ERROR,
            RetryErrorType.RATE_LIMIT
        ]
    
    metrics = RetryMetrics()
    start_time = time.time()
    last_exception = None
    
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        attempt_start = time.time()
        
        try:
            metrics.total_attempts += 1
            result = func()
            
            if attempt > 0:
                metrics.successful_retries += 1
                retry_duration = time.time() - start_time
                metrics.total_retry_time += retry_duration
                
                logger.info(f"[Retry] Success on attempt {attempt + 1}/{max_retries + 1} "
                           f"after {retry_duration:.2f}s" + 
                           (f" ({context})" if context else ""))
            
            return result
            
        except Exception as e:
            last_exception = e
            attempt_duration = time.time() - attempt_start
            error_type = classify_error_for_retry(e)
            
            # Track error metrics
            error_key = error_type.value
            metrics.error_counts[error_key] = metrics.error_counts.get(error_key, 0) + 1
            
            # Check if we should retry this error type
            should_retry = error_type in retry_on
            
            # Check timeout
            total_elapsed = time.time() - start_time
            if timeout and total_elapsed >= timeout:
                logger.error(f"[Retry] Total timeout {timeout}s exceeded after {attempt + 1} attempts" +
                           (f" ({context})" if context else ""))
                break
            
            # Last attempt or non-retryable error
            if attempt >= max_retries or not should_retry:
                metrics.failed_retries += 1
                
                if not should_retry:
                    logger.error(f"[Retry] Non-retryable error {error_type.value}: {e}" +
                               (f" ({context})" if context else ""))
                else:
                    logger.error(f"[Retry] Max retries ({max_retries}) exceeded: {e}" +
                               (f" ({context})" if context else ""))
                break
            
            # Calculate backoff delay
            delay = calculate_backoff_delay(
                attempt, 
                base_delay, 
                max_delay, 
                jitter, 
                exponential=True
            )
            
            metrics.backoff_times.append(delay)
            metrics.last_retry_timestamp = time.time()
            
            logger.warning(f"[Retry] Attempt {attempt + 1}/{max_retries + 1} failed "
                         f"({error_type.value}): {e}. Retrying in {delay:.2f}s" +
                         (f" ({context})" if context else ""))
            
            time.sleep(delay)
    
    # Log final retry metrics
    total_time = time.time() - start_time
    metrics.total_retry_time = total_time
    
    logger.error(f"[Retry] All attempts failed in {total_time:.2f}s. "
                f"Attempts: {metrics.total_attempts}, "
                f"Error distribution: {metrics.error_counts}" +
                (f" ({context})" if context else ""))
    
    raise last_exception

def rate_limited(service: str):
    """Enhanced decorator for rate limiting with retry support"""
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
            context = f"{service}:{func.__name__}"
            
            # Wait for token availability with timeout
            wait_start = time.time()
            while not limiter.consume():
                elapsed = time.time() - wait_start
                if elapsed > timeout:
                    logger.error(f"[RateLimit] Wait timeout exceeded {timeout}s for {context}")
                    raise TimeoutError(f"Rate limit wait exceeded {timeout}s for {service}")
                time.sleep(0.1)  # Poll every 100ms
            
            # Call through circuit breaker
            try:
                return circuit.call(func, *args, **kwargs)
            except Exception as e:
                logger.error(f"[RateLimit] Circuit breaker failure for {context}: {e}")
                raise
        return wrapper
    return decorator

# Enhanced retry decorators for specific services
@rate_limited("moonshot")
def moonshot_chat_limited(messages, temperature=0.4, timeout=15, max_retries=3):
    """Moonshot chat with rate limiting and intelligent retry"""
    from moonshot_client import moonshot_chat
    
    def _call():
        return moonshot_chat(messages, temperature, timeout)
    
    return retry_with_backoff(
        _call,
        max_retries=max_retries,
        base_delay=1.0,
        max_delay=30.0,
        context="moonshot_chat"
    )

@rate_limited("openai")
def openai_chat_limited(messages, model="gpt-4o-mini", temperature=0.4, timeout=20, max_retries=2):
    """OpenAI chat with rate limiting and retry"""
    from openai_client_wrapper import openai_chat_completion
    
    def _call():
        return openai_chat_completion(messages, model, temperature, timeout)
    
    return retry_with_backoff(
        _call,
        max_retries=max_retries,
        base_delay=2.0,
        max_delay=45.0,
        context="openai_chat"
    )

@rate_limited("deepseek")
def deepseek_chat_limited(messages, temperature=0.3, timeout=10, max_retries=3):
    """DeepSeek chat with rate limiting and retry"""
    from deepseek_client import deepseek_chat
    
    def _call():
        return deepseek_chat(messages, temperature, timeout)
    
    return retry_with_backoff(
        _call,
        max_retries=max_retries,
        base_delay=1.5,
        max_delay=20.0,
        context="deepseek_chat"
    )

@rate_limited("xai")  
def xai_chat_limited(messages, temperature=0.3, timeout=15, max_retries=2):
    """XAI chat with rate limiting and retry"""
    from xai_client import xai_chat
    
    def _call():
        return xai_chat(messages, temperature, timeout)
    
    return retry_with_backoff(
        _call,
        max_retries=max_retries,
        base_delay=2.0,
        max_delay=30.0,
        context="xai_chat"
    )

def get_comprehensive_rate_limiter_stats():
    """Get detailed rate limiting stats for monitoring and analysis"""
    return {
        "openai": openai_limiter.get_comprehensive_metrics(),
        "xai": xai_limiter.get_comprehensive_metrics(),
        "deepseek": deepseek_limiter.get_comprehensive_metrics(),
        "moonshot": moonshot_limiter.get_comprehensive_metrics(),
        "timestamp": time.time()
    }

def get_rate_limiter_stats():
    """Get basic rate limiting stats for backward compatibility"""
    return {
        "openai": openai_limiter.get_metrics(),
        "xai": xai_limiter.get_metrics(),
        "deepseek": deepseek_limiter.get_metrics(),
        "moonshot": moonshot_limiter.get_metrics()
    }

def get_all_rate_limit_stats():
    """Alias for get_comprehensive_rate_limiter_stats"""
    return get_comprehensive_rate_limiter_stats()

def get_comprehensive_circuit_breaker_stats():
    """Get detailed circuit breaker status for monitoring and analysis"""
    return {
        "openai": openai_circuit.get_comprehensive_metrics(),
        "xai": xai_circuit.get_comprehensive_metrics(),
        "deepseek": deepseek_circuit.get_comprehensive_metrics(),
        "moonshot": moonshot_circuit.get_comprehensive_metrics(),
        "timestamp": time.time()
    }

def get_circuit_breaker_stats():
    """Get basic circuit breaker status for backward compatibility"""
    comprehensive_stats = get_comprehensive_circuit_breaker_stats()
    
    # Convert to legacy format
    legacy_stats = {}
    for service, stats in comprehensive_stats.items():
        if service == "timestamp":
            continue
        legacy_stats[service] = {
            "state": stats["state"],
            "failure_count": stats["failure_count"],
            "last_failure": stats["last_failure"],
            "service": stats["service"]
        }
    
    return legacy_stats

def get_all_circuit_breaker_stats():
    """Alias for get_comprehensive_circuit_breaker_stats"""
    return get_comprehensive_circuit_breaker_stats()

def analyze_frequent_issues() -> Dict[str, Any]:
    """Analyze logs to identify frequent issues and patterns"""
    rate_stats = get_comprehensive_rate_limiter_stats()
    circuit_stats = get_comprehensive_circuit_breaker_stats()
    
    issues = []
    recommendations = []
    
    for service in ["openai", "xai", "deepseek", "moonshot"]:
        # Rate limiting analysis
        rl_stats = rate_stats[service]
        cb_stats = circuit_stats[service]
        
        # High denial rate
        if rl_stats["denied_requests"] > 0:
            denial_rate = rl_stats["denied_requests"] / rl_stats["total_requests"]
            if denial_rate > 0.1:  # >10% denial rate
                issues.append({
                    "service": service,
                    "type": "high_rate_limit_denial",
                    "severity": "high" if denial_rate > 0.3 else "medium",
                    "details": f"Denial rate: {denial_rate:.1%}",
                    "recommendation": f"Increase token limit or reduce request frequency for {service}"
                })
        
        # Circuit breaker issues
        if cb_stats["circuit_opens"] > 0:
            issues.append({
                "service": service,
                "type": "circuit_breaker_activations",
                "severity": "high" if cb_stats["state"] == "open" else "medium",
                "details": f"Circuit opened {cb_stats['circuit_opens']} times",
                "recommendation": f"Investigate error patterns for {service}: {cb_stats['error_types']}"
            })
        
        # High failure rate
        if cb_stats["total_requests"] > 10 and cb_stats["failure_rate"] > 0.2:
            issues.append({
                "service": service,
                "type": "high_failure_rate", 
                "severity": "high",
                "details": f"Failure rate: {cb_stats['failure_rate']:.1%}",
                "recommendation": f"Check {service} service health and API status"
            })
        
        # Slow response times
        if cb_stats["avg_response_time"] > 10.0:  # >10s average
            issues.append({
                "service": service,
                "type": "slow_response_times",
                "severity": "medium",
                "details": f"Avg response: {cb_stats['avg_response_time']:.1f}s",
                "recommendation": f"Consider timeout tuning or alternative models for {service}"
            })
    
    # Generate summary recommendations
    if any(issue["severity"] == "high" for issue in issues):
        recommendations.extend([
            "Consider implementing request queuing during peak times",
            "Review and optimize retry strategies",
            "Monitor API provider status pages",
            "Implement graceful degradation to backup providers"
        ])
    
    return {
        "issues_found": len(issues),
        "issues": issues,
        "recommendations": recommendations,
        "analysis_timestamp": time.time(),
        "summary": {
            "total_services": 4,
            "healthy_services": len([s for s in ["openai", "xai", "deepseek", "moonshot"] 
                                   if circuit_stats[s]["health_status"] == "healthy"]),
            "degraded_services": len([s for s in ["openai", "xai", "deepseek", "moonshot"] 
                                    if circuit_stats[s]["health_status"] == "degraded"]),
            "critical_services": len([s for s in ["openai", "xai", "deepseek", "moonshot"] 
                                    if circuit_stats[s]["health_status"] == "critical"])
        }
    }

def log_monitoring_summary():
    """Log comprehensive monitoring summary"""
    try:
        analysis = analyze_frequent_issues()
        rate_stats = get_comprehensive_rate_limiter_stats()
        circuit_stats = get_comprehensive_circuit_breaker_stats()
        
        logger.info("="*80)
        logger.info("🔍 LLM RATE LIMITING & CIRCUIT BREAKER MONITORING SUMMARY")
        logger.info("="*80)
        
        # Overall health
        summary = analysis["summary"]
        logger.info(f"🏥 Overall Health: {summary['healthy_services']}/4 healthy, "
                   f"{summary['degraded_services']} degraded, {summary['critical_services']} critical")
        
        # Service-specific stats
        for service in ["openai", "xai", "deepseek", "moonshot"]:
            rl = rate_stats[service]
            cb = circuit_stats[service]
            
            logger.info(f"")
            logger.info(f"🤖 {service.upper()}")
            logger.info(f"   Rate Limiting: {rl['requests_last_minute']} req/min, "
                       f"{rl['utilization']:.1%} utilization, "
                       f"health: {rl['health_status']}")
            logger.info(f"   Circuit Breaker: {cb['state']} state, "
                       f"{cb['failure_rate']:.1%} failure rate, "
                       f"{cb['avg_response_time']:.1f}s avg response")
            
            if cb['error_types']:
                top_error = max(cb['error_types'].items(), key=lambda x: x[1])
                logger.info(f"   Top Error: {top_error[0]} ({top_error[1]} occurrences)")
        
        # Issues and recommendations
        if analysis["issues"]:
            logger.warning(f"⚠️  {analysis['issues_found']} issues identified:")
            for issue in analysis["issues"][:5]:  # Show top 5
                logger.warning(f"   - {issue['service']}: {issue['type']} ({issue['severity']})")
                logger.warning(f"     {issue['details']} → {issue['recommendation']}")
        else:
            logger.info("✅ No significant issues detected")
        
        if analysis["recommendations"]:
            logger.info(f"💡 Recommendations:")
            for rec in analysis["recommendations"]:
                logger.info(f"   - {rec}")
        
        logger.info("="*80)
        
    except Exception as e:
        logger.error(f"Failed to generate monitoring summary: {e}")

def get_health_status():
    """Enhanced overall system health status"""
    rate_stats = get_comprehensive_rate_limiter_stats()
    circuit_stats = get_comprehensive_circuit_breaker_stats()
    analysis = analyze_frequent_issues()
    
    overall_status = "healthy"
    issues = []
    
    for service in ["openai", "xai", "deepseek", "moonshot"]:
        # Check rate limiting health
        rl_health = rate_stats[service]["health_status"]
        cb_health = circuit_stats[service]["health_status"]
        
        if cb_health == "critical" or rl_health == "critical":
            issues.append(f"{service}_critical")
            overall_status = "critical"
        elif cb_health == "degraded" or rl_health == "degraded":
            issues.append(f"{service}_degraded")
            if overall_status == "healthy":
                overall_status = "degraded"
    
    # High-level issue detection
    if analysis["issues_found"] > 5:
        overall_status = "degraded" if overall_status != "critical" else "critical"
    
    return {
        "status": overall_status,
        "issues": issues,
        "timestamp": time.time(),
        "services_available": [s for s in ["openai", "xai", "deepseek", "moonshot"] 
                              if circuit_stats[s]["state"] != "open"],
        "total_issues": analysis["issues_found"],
        "critical_issues": len([i for i in analysis["issues"] if i["severity"] == "high"]),
        "health_score": (analysis["summary"]["healthy_services"] / 4) * 100
    }

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
            old_state = circuit.state
            circuit.failure_count = 0
            circuit.state = "closed"
            circuit.last_failure_time = None
            circuit._record_state_transition(old_state, "closed", "manual_reset")
            logger.info(f"[CircuitBreaker] {service} circuit manually reset")
        return True
    return False

def reset_all_circuit_breakers():
    """Reset all circuit breakers (emergency admin function)"""
    results = {}
    for service in ["openai", "xai", "deepseek", "moonshot"]:
        results[service] = reset_circuit_breaker(service)
    
    logger.warning(f"[CircuitBreaker] Manual reset of all circuit breakers: {results}")
    return results

def get_system_performance_report() -> Dict[str, Any]:
    """Generate comprehensive system performance report"""
    try:
        rate_stats = get_comprehensive_rate_limiter_stats()
        circuit_stats = get_comprehensive_circuit_breaker_stats()
        analysis = analyze_frequent_issues()
        health = get_health_status()
        
        # Calculate aggregate metrics
        total_requests = sum(cb["total_requests"] for cb in circuit_stats.values() if isinstance(cb, dict))
        total_successes = sum(cb["successful_requests"] for cb in circuit_stats.values() if isinstance(cb, dict))
        total_failures = sum(cb["failed_requests"] for cb in circuit_stats.values() if isinstance(cb, dict))
        
        overall_success_rate = (total_successes / total_requests) if total_requests > 0 else 0.0
        overall_failure_rate = (total_failures / total_requests) if total_requests > 0 else 0.0
        
        # Service availability
        available_services = health["services_available"]
        availability_percentage = (len(available_services) / 4) * 100
        
        report = {
            "report_timestamp": time.time(),
            "executive_summary": {
                "overall_health": health["status"],
                "health_score": health["health_score"],
                "service_availability": f"{len(available_services)}/4 ({availability_percentage:.0f}%)",
                "overall_success_rate": f"{overall_success_rate:.1%}",
                "issues_detected": analysis["issues_found"],
                "critical_issues": health["critical_issues"]
            },
            "performance_metrics": {
                "total_requests": total_requests,
                "successful_requests": total_successes,
                "failed_requests": total_failures,
                "success_rate": overall_success_rate,
                "failure_rate": overall_failure_rate
            },
            "service_details": {
                "rate_limiting": rate_stats,
                "circuit_breakers": circuit_stats
            },
            "issue_analysis": analysis,
            "health_status": health,
            "recommendations": {
                "immediate": [issue for issue in analysis["issues"] if issue["severity"] == "high"],
                "optimization": [issue for issue in analysis["issues"] if issue["severity"] == "medium"],
                "general": analysis["recommendations"]
            }
        }
        
        return report
        
    except Exception as e:
        logger.error(f"Failed to generate system performance report: {e}")
        return {
            "error": str(e),
            "report_timestamp": time.time(),
            "status": "report_generation_failed"
        }

def start_monitoring_thread(interval: int = 300):
    """Start background monitoring thread (5 min default)"""
    def monitor_worker():
        while True:
            try:
                log_monitoring_summary()
                time.sleep(interval)
            except Exception as e:
                logger.error(f"Monitoring thread error: {e}")
                time.sleep(60)  # Retry in 1 minute on error
    
    monitor_thread = threading.Thread(target=monitor_worker, daemon=True, name="LLMMonitoring")
    monitor_thread.start()
    logger.info(f"Started LLM monitoring thread with {interval}s interval")
    return monitor_thread

# Utility functions for external integrations
def get_service_status(service: str) -> Dict[str, Any]:
    """Get detailed status for a specific service"""
    if service not in ["openai", "xai", "deepseek", "moonshot"]:
        return {"error": f"Unknown service: {service}"}
    
    rate_stats = get_comprehensive_rate_limiter_stats()
    circuit_stats = get_comprehensive_circuit_breaker_stats()
    
    return {
        "service": service,
        "rate_limiting": rate_stats[service],
        "circuit_breaker": circuit_stats[service],
        "timestamp": time.time(),
        "is_available": circuit_stats[service]["state"] != "open",
        "health_summary": {
            "rate_limit_health": rate_stats[service]["health_status"],
            "circuit_breaker_health": circuit_stats[service]["health_status"],
            "overall_health": "healthy" if (
                rate_stats[service]["health_status"] == "healthy" and 
                circuit_stats[service]["health_status"] == "healthy"
            ) else "degraded"
        }
    }
