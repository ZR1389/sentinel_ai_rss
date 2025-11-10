# circuit_breaker.py – Async circuit breaker with production features
from __future__ import annotations
import asyncio
import time
import random
import logging
from enum import Enum
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass
from config import CONFIG
from metrics import METRICS

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

@dataclass
class CircuitMetrics:
    """Detailed metrics for monitoring"""
    total_requests: int = 0
    failed_requests: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    
    @property
    def failure_rate(self) -> float:
        return self.failed_requests / max(self.total_requests, 1)
    
    def reset(self):
        self.total_requests = 0
        self.failed_requests = 0

class AsyncCircuitBreaker:
    """Async-compatible circuit breaker with jitter and detailed metrics."""
    
    def __init__(
        self,
        name: str,
        failure_threshold: float = 0.5,
        recovery_timeout: float = 60.0,
        request_threshold: int = 5,
        consecutive_failures_threshold: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.request_threshold = request_threshold
        self.consecutive_failures_threshold = consecutive_failures_threshold
        
        self.state = CircuitState.CLOSED
        self.metrics = CircuitMetrics()
        self.last_state_change = time.time()
        
        # Backoff with jitter
        self.base_delay = 1.0
        self.max_delay = 300.0
        self.backoff_multiplier = 2.0
        self.jitter_range = 0.1
        
        self._lock = asyncio.Lock()
        logger.info(f"[CB:{self.name}] Initialized with failure_threshold={failure_threshold}")
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker."""
        async with self._lock:
            # Attempt recovery if needed
            if self._should_attempt_recovery():
                self._transition(CircuitState.HALF_OPEN, "Testing recovery")
            
            # Fast-fail if open
            if self.state == CircuitState.OPEN:
                retry_in = self._retry_delay()
                raise CircuitBreakerOpen(self.name, retry_in)
            
            # Track half-open attempts
            if self.state == CircuitState.HALF_OPEN:
                if self.metrics.consecutive_successes >= 2:  # Need 2 successes to close
                    self._transition(CircuitState.CLOSED, "Recovery successful")
                elif self.metrics.consecutive_failures > 0:
                    self._transition(CircuitState.OPEN, "Recovery failed")
        
        # Execute outside lock
        return await self._execute(func, *args, **kwargs)
    
    async def _execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute and track result."""
        start = time.time()
        try:
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=30.0)
            
            async with self._lock:
                self.metrics.total_requests += 1
                self.metrics.success_requests += 1
                self.metrics.consecutive_successes += 1
                self.metrics.consecutive_failures = 0
                self.metrics.last_success_time = time.time()
                
                if self.state == CircuitState.HALF_OPEN:
                    logger.info(f"[CB:{self.name}] Recovery attempt succeeded")
            
            METRICS.timing(f"cb_{self.name}_success", (time.time() - start) * 1000)
            return result
            
        except Exception as e:
            async with self._lock:
                self.metrics.total_requests += 1
                self.metrics.failed_requests += 1
                self.metrics.consecutive_failures += 1
                self.metrics.consecutive_successes = 0
                self.metrics.last_failure_time = time.time()
                
                if self._should_open():
                    self._transition(CircuitState.OPEN, f"Threshold exceeded: {e}")
                elif self.state == CircuitState.HALF_OPEN:
                    self._transition(CircuitState.OPEN, f"Recovery test failed: {e}")
            
            METRICS.timing(f"cb_{self.name}_failure", (time.time() - start) * 1000)
            METRICS.increment(f"cb_{self.name}_errors")
            raise
    
    def _should_open(self) -> bool:
        """Check if circuit should open."""
        return (
            self.metrics.consecutive_failures >= self.consecutive_failures_threshold
            or (
                self.metrics.total_requests >= self.request_threshold
                and self.metrics.failure_rate >= self.failure_threshold
            )
        )
    
    def _should_attempt_recovery(self) -> bool:
        """Check if we've been open long enough to try recovery."""
        return (
            self.state == CircuitState.OPEN
            and time.time() - self.last_state_change >= self.recovery_timeout
        )
    
    def _transition(self, new_state: CircuitState, reason: str):
        """Transition to new state."""
        old_state = self.state
        self.state = new_state
        self.last_state_change = time.time()
        
        logger.warning(
            f"[CB:{self.name}] {old_state.value} → {new_state.value}. {reason}. "
            f"Failure rate: {self.metrics.failure_rate:.1%}"
        )
        
        if new_state == CircuitState.CLOSED:
            self.metrics.reset()
            self.metrics.consecutive_successes = 0
    
    def _retry_delay(self) -> float:
        """Calculate next retry delay with jitter."""
        delay = min(
            self.base_delay * (self.backoff_multiplier ** self.metrics.consecutive_failures),
            self.max_delay,
        )
        jitter = delay * self.jitter_range * (random.random() * 2 - 1)
        return max(0.1, delay + jitter)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_rate": self.metrics.failure_rate,
            "total_requests": self.metrics.total_requests,
            "consecutive_failures": self.metrics.consecutive_failures,
            "retry_delay": self._retry_delay() if self.state == CircuitState.OPEN else 0,
        }

class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""
    def __init__(self, name: str, retry_after: float):
        super().__init__(f"Circuit breaker '{name}' is OPEN. Retry in {retry_after:.1f}s")
        self.name = name
        self.retry_after = retry_after

# Global Moonshot circuit breaker
MOONSHOT_CB = AsyncCircuitBreaker(
    name="moonshot",
    failure_threshold=CONFIG.cb_failure_threshold,
    recovery_timeout=CONFIG.cb_recovery_timeout_sec,
    request_threshold=CONFIG.cb_request_volume_threshold,
)