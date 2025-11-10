"""
Moonshot Circuit Breaker - API Protection and Failure Recovery

This module implements a circuit breaker pattern specifically for Moonshot API calls
to prevent cascading failures and provide graceful degradation.

Circuit Breaker States:
- CLOSED: Normal operation, requests pass through
- OPEN: API is failing, requests are blocked for a cooldown period
- HALF_OPEN: Testing if API has recovered, limited requests allowed

Features:
- Configurable failure thresholds and timeouts
- Exponential backoff with jitter
- Thread-safe operation
- Metrics collection integration
- Automatic recovery testing
"""

import time
import random
import threading
from enum import Enum
from typing import Optional, Callable, Any
from dataclasses import dataclass
from datetime import datetime, timedelta


class CircuitBreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and requests are blocked"""
    
    def __init__(self, message: str, retry_after: float = 0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior"""
    failure_threshold: int = 5  # Number of consecutive failures to trip breaker
    success_threshold: int = 2  # Number of successes needed to close breaker
    timeout: float = 60.0  # Seconds to wait before trying half-open
    max_timeout: float = 300.0  # Maximum timeout (5 minutes)
    backoff_multiplier: float = 1.5  # Exponential backoff factor
    jitter_factor: float = 0.1  # Random jitter to prevent thundering herd


class MoonshotCircuitBreaker:
    """
    Circuit breaker for Moonshot API calls with exponential backoff
    """
    
    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.current_timeout = self.config.timeout
        self.lock = threading.RLock()
        
        # Metrics tracking
        self.total_calls = 0
        self.total_failures = 0
        self.total_successes = 0
        self.state_transitions = []
        
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker protection
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerOpenError: When circuit breaker is open
            Exception: Any exception from the wrapped function
        """
        with self.lock:
            self.total_calls += 1
            
            # Check if we should block the request
            if self._should_block_request():
                retry_after = self._get_retry_after()
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN. Retry after {retry_after:.1f} seconds",
                    retry_after=retry_after
                )
            
            # Allow request to proceed
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
                
            except Exception as e:
                self._on_failure()
                raise e
    
    def _should_block_request(self) -> bool:
        """Check if request should be blocked based on current state"""
        if self.state == CircuitBreakerState.CLOSED:
            return False
            
        if self.state == CircuitBreakerState.HALF_OPEN:
            # Allow limited requests to test recovery
            return False
            
        if self.state == CircuitBreakerState.OPEN:
            # Check if timeout has elapsed
            if self.last_failure_time is None:
                return True
                
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.current_timeout:
                # Try half-open state
                self._transition_to_half_open()
                return False
            
            return True
            
        return False
    
    def _get_retry_after(self) -> float:
        """Calculate retry delay with jitter"""
        if self.last_failure_time is None:
            return self.current_timeout
            
        elapsed = time.time() - self.last_failure_time
        remaining = max(0, self.current_timeout - elapsed)
        
        # Add jitter to prevent thundering herd
        jitter = remaining * self.config.jitter_factor * random.random()
        return remaining + jitter
    
    def _on_success(self):
        """Handle successful request"""
        self.total_successes += 1
        
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self._transition_to_closed()
        elif self.state == CircuitBreakerState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0
    
    def _on_failure(self):
        """Handle failed request"""
        self.total_failures += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitBreakerState.CLOSED:
            self.failure_count += 1
            if self.failure_count >= self.config.failure_threshold:
                self._transition_to_open()
        elif self.state == CircuitBreakerState.HALF_OPEN:
            # Failure during half-open means we're not recovered yet
            self._transition_to_open()
    
    def _transition_to_open(self):
        """Transition to OPEN state"""
        old_state = self.state
        self.state = CircuitBreakerState.OPEN
        self.success_count = 0
        
        # Exponential backoff with max limit
        self.current_timeout = min(
            self.current_timeout * self.config.backoff_multiplier,
            self.config.max_timeout
        )
        
        self.state_transitions.append({
            'timestamp': datetime.now(),
            'from_state': old_state.value,
            'to_state': self.state.value,
            'timeout': self.current_timeout
        })
        
        print(f"[CircuitBreaker] State transition: {old_state.value} -> {self.state.value} "
              f"(timeout: {self.current_timeout:.1f}s)")
    
    def _transition_to_half_open(self):
        """Transition to HALF_OPEN state"""
        old_state = self.state
        self.state = CircuitBreakerState.HALF_OPEN
        self.success_count = 0
        
        self.state_transitions.append({
            'timestamp': datetime.now(),
            'from_state': old_state.value,
            'to_state': self.state.value,
            'timeout': self.current_timeout
        })
        
        print(f"[CircuitBreaker] State transition: {old_state.value} -> {self.state.value}")
    
    def _transition_to_closed(self):
        """Transition to CLOSED state"""
        old_state = self.state
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        
        # Reset timeout to initial value on recovery
        self.current_timeout = self.config.timeout
        
        self.state_transitions.append({
            'timestamp': datetime.now(),
            'from_state': old_state.value,
            'to_state': self.state.value,
            'timeout': self.current_timeout
        })
        
        print(f"[CircuitBreaker] State transition: {old_state.value} -> {self.state.value} "
              f"(recovered)")
    
    def get_stats(self) -> dict:
        """Get circuit breaker statistics"""
        with self.lock:
            return {
                'state': self.state.value,
                'failure_count': self.failure_count,
                'success_count': self.success_count,
                'total_calls': self.total_calls,
                'total_failures': self.total_failures,
                'total_successes': self.total_successes,
                'current_timeout': self.current_timeout,
                'last_failure_time': self.last_failure_time,
                'failure_rate': self.total_failures / max(self.total_calls, 1),
                'state_transitions': len(self.state_transitions)
            }
    
    def reset(self):
        """Reset circuit breaker to initial state"""
        with self.lock:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
            self.current_timeout = self.config.timeout


# Global instance for Moonshot API
_moonshot_circuit_breaker: Optional[MoonshotCircuitBreaker] = None
_circuit_breaker_lock = threading.Lock()


def get_moonshot_circuit_breaker() -> MoonshotCircuitBreaker:
    """
    Get the global Moonshot circuit breaker instance (singleton)
    """
    global _moonshot_circuit_breaker
    
    if _moonshot_circuit_breaker is None:
        with _circuit_breaker_lock:
            if _moonshot_circuit_breaker is None:
                # Configure for Moonshot API characteristics
                config = CircuitBreakerConfig(
                    failure_threshold=3,  # Trip after 3 failures
                    success_threshold=2,  # Need 2 successes to recover
                    timeout=30.0,  # Start with 30 second timeout
                    max_timeout=300.0,  # Max 5 minute timeout
                    backoff_multiplier=2.0,  # Double timeout each time
                    jitter_factor=0.2  # 20% jitter
                )
                _moonshot_circuit_breaker = MoonshotCircuitBreaker(config)
    
    return _moonshot_circuit_breaker


def reset_moonshot_circuit_breaker():
    """Reset the global circuit breaker (for testing)"""
    global _moonshot_circuit_breaker
    with _circuit_breaker_lock:
        if _moonshot_circuit_breaker:
            _moonshot_circuit_breaker.reset()


# Convenience function for direct API protection
def protected_moonshot_call(func: Callable, *args, **kwargs) -> Any:
    """
    Execute a function with circuit breaker protection
    
    Args:
        func: Function to execute
        *args: Function arguments
        **kwargs: Function keyword arguments
        
    Returns:
        Function result
        
    Raises:
        CircuitBreakerOpenError: When circuit breaker is open
        Exception: Any exception from the wrapped function
    """
    circuit_breaker = get_moonshot_circuit_breaker()
    return circuit_breaker.call(func, *args, **kwargs)
