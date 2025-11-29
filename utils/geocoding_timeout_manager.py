# geocoding_timeout_manager.py — Total Timeout Management for Geocoding Chain
"""
Prevents geocoding cascade failures by implementing total timeout across the entire geocoding chain:
cache → city_utils → reverse_geo → fallback

Without this, if each step takes 5s, location extraction could take 20s+ per alert.

Features:
- Total timeout across all geocoding steps
- Individual step timeouts  
- Async-compatible timeouts
- Graceful degradation when timeouts occur
- Performance monitoring and metrics
"""

import time
import logging
from typing import Optional, Tuple, Dict, Any, Callable
from dataclasses import dataclass
import threading
import concurrent.futures

logger = logging.getLogger("geocoding_timeout")

@dataclass
class GeocodingMetrics:
    """Metrics for geocoding performance monitoring"""
    total_requests: int = 0
    cache_hits: int = 0
    city_utils_calls: int = 0
    reverse_geo_calls: int = 0
    timeouts: int = 0
    total_time: float = 0.0
    cache_time: float = 0.0
    city_utils_time: float = 0.0
    reverse_geo_time: float = 0.0
    
    def average_time(self) -> float:
        return self.total_time / max(1, self.total_requests)
    
    def cache_hit_rate(self) -> float:
        return self.cache_hits / max(1, self.total_requests)
    
    def timeout_rate(self) -> float:
        return self.timeouts / max(1, self.total_requests)

class GeocodingTimeoutError(Exception):
    """Raised when geocoding operations exceed timeout"""
    
    def __init__(self, message: str, elapsed_time: float = 0.0, step: str = "unknown"):
        super().__init__(message)
        self.elapsed_time = elapsed_time
        self.step = step

class GeocodingTimeoutManager:
    """
    Manages timeouts for the entire geocoding chain to prevent cascade failures.
    
    Implements progressive timeouts:
    - Total timeout: Maximum time for entire geocoding operation  
    - Step timeouts: Maximum time per individual step
    - Early termination: Stops chain if total timeout approaches
    """
    
    def __init__(self,
                 total_timeout: float = 10.0,      # Total time for entire geocoding chain
                 cache_timeout: float = 1.0,       # Cache lookup timeout
                 city_utils_timeout: float = 5.0,  # City utils geocoding timeout  
                 reverse_geo_timeout: float = 3.0, # Reverse geocoding timeout
                 enable_monitoring: bool = True):   # Enable performance monitoring
        
        self.total_timeout = total_timeout
        self.cache_timeout = cache_timeout
        self.city_utils_timeout = city_utils_timeout
        self.reverse_geo_timeout = reverse_geo_timeout
        self.enable_monitoring = enable_monitoring
        
        self.metrics = GeocodingMetrics()
        self._lock = threading.Lock()
        
        logger.info(f"[GEOCODING_TIMEOUT] Initialized: total={total_timeout}s, "
                   f"cache={cache_timeout}s, city_utils={city_utils_timeout}s, "
                   f"reverse_geo={reverse_geo_timeout}s")
    
    def _record_timeout(self, step: str, elapsed_time: float):
        """Record timeout occurrence for monitoring"""
        if not self.enable_monitoring:
            return
            
        with self._lock:
            self.metrics.timeouts += 1
            logger.warning(f"[GEOCODING_TIMEOUT] {step} timed out after {elapsed_time:.2f}s")
    
    def _record_step_time(self, step: str, duration: float):
        """Record step timing for monitoring"""
        if not self.enable_monitoring:
            return
            
        with self._lock:
            if step == "cache":
                self.metrics.cache_time += duration
            elif step == "city_utils":
                self.metrics.city_utils_time += duration  
            elif step == "reverse_geo":
                self.metrics.reverse_geo_time += duration
    
    def _run_sync_with_timeout(self, func: Callable, timeout: float, step: str, *args, **kwargs):
        """Execute synchronous function with timeout"""
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            
            try:
                result = future.result(timeout=timeout)
                duration = time.time() - start_time
                self._record_step_time(step, duration)
                return result
                
            except concurrent.futures.TimeoutError:
                elapsed = time.time() - start_time
                self._record_timeout(step, elapsed)
                raise GeocodingTimeoutError(
                    f"{step} timed out after {elapsed:.2f}s (limit: {timeout:.2f}s)",
                    elapsed, step
                )
    
    def geocode_with_timeout(self, 
                           city: str, 
                           country: Optional[str] = None,
                           cache_lookup: Optional[Callable] = None,
                           city_utils_lookup: Optional[Callable] = None,
                           reverse_geo_lookup: Optional[Callable] = None,
                           cache_store: Optional[Callable] = None) -> Tuple[Optional[float], Optional[float]]:
        """
        Synchronous geocoding chain with comprehensive timeout management.
        
        Args:
            city: City name to geocode
            country: Optional country name
            cache_lookup: Function for cache lookup: (city, country) -> (lat, lon) or None
            city_utils_lookup: Function for city utils lookup: (city, country) -> (lat, lon)
            reverse_geo_lookup: Function for reverse geo lookup: (query) -> (lat, lon)
            cache_store: Function for storing result in cache: (city, country, lat, lon) -> None
            
        Returns:
            Tuple of (latitude, longitude) or (None, None) if failed/timeout
        """
        operation_start = time.time()
        
        if self.enable_monitoring:
            with self._lock:
                self.metrics.total_requests += 1
        
        # Step 1: Cache lookup (fast)
        if cache_lookup:
            try:
                remaining = self.total_timeout - (time.time() - operation_start)
                if remaining <= 0:
                    raise GeocodingTimeoutError("No time remaining for cache lookup", 0, "cache")
                
                timeout = min(self.cache_timeout, remaining)
                result = self._run_sync_with_timeout(cache_lookup, timeout, "cache", city, country)
                
                if result and result[0] is not None and result[1] is not None:
                    logger.debug(f"[GEOCODING_TIMEOUT] Cache hit for {city}, {country}")
                    if self.enable_monitoring:
                        with self._lock:
                            self.metrics.cache_hits += 1
                    return result
                    
            except GeocodingTimeoutError:
                logger.debug(f"[GEOCODING_TIMEOUT] Cache lookup timed out for {city}, {country}")
            except Exception as e:
                logger.debug(f"[GEOCODING_TIMEOUT] Cache lookup failed: {e}")
        
        # Step 2: City utils lookup (main geocoding)
        if city_utils_lookup:
            try:
                remaining = self.total_timeout - (time.time() - operation_start)
                if remaining <= 0:
                    raise GeocodingTimeoutError("No time remaining for city utils lookup", 0, "city_utils")
                
                timeout = min(self.city_utils_timeout, remaining)
                result = self._run_sync_with_timeout(city_utils_lookup, timeout, "city_utils", city, country)
                
                if result and result[0] is not None and result[1] is not None:
                    logger.debug(f"[GEOCODING_TIMEOUT] City utils success for {city}, {country}")
                    if self.enable_monitoring:
                        with self._lock:
                            self.metrics.city_utils_calls += 1
                    
                    # Store in cache if available
                    if cache_store:
                        try:
                            cache_store(city, country, result[0], result[1])
                        except Exception as e:
                            logger.debug(f"[GEOCODING_TIMEOUT] Cache store failed: {e}")
                    
                    return result
                    
            except GeocodingTimeoutError:
                logger.debug(f"[GEOCODING_TIMEOUT] City utils timed out for {city}, {country}")
            except Exception as e:
                logger.debug(f"[GEOCODING_TIMEOUT] City utils lookup failed: {e}")
        
        # Step 3: Reverse geo lookup (fallback)
        if reverse_geo_lookup:
            try:
                remaining = self.total_timeout - (time.time() - operation_start)
                if remaining <= 0:
                    logger.warning("[GEOCODING_TIMEOUT] No time remaining for reverse geo lookup")
                    total_elapsed = time.time() - operation_start
                    if total_elapsed >= self.total_timeout:
                        raise GeocodingTimeoutError("Total timeout exceeded", total_elapsed, "total")
                    return (None, None)
                
                timeout = min(self.reverse_geo_timeout, remaining)
                query = f"{city}, {country}" if country else city
                result = self._run_sync_with_timeout(reverse_geo_lookup, timeout, "reverse_geo", query)
                
                if result and result[0] is not None and result[1] is not None:
                    logger.debug(f"[GEOCODING_TIMEOUT] Reverse geo success for {city}, {country}")
                    if self.enable_monitoring:
                        with self._lock:
                            self.metrics.reverse_geo_calls += 1
                    
                    # Store in cache if available
                    if cache_store:
                        try:
                            cache_store(city, country, result[0], result[1])
                        except Exception as e:
                            logger.debug(f"[GEOCODING_TIMEOUT] Cache store failed: {e}")
                    
                    return result
                    
            except GeocodingTimeoutError:
                logger.debug(f"[GEOCODING_TIMEOUT] Reverse geo timed out for {city}, {country}")
            except Exception as e:
                logger.debug(f"[GEOCODING_TIMEOUT] Reverse geo lookup failed: {e}")
        
        # Check if we exceeded total timeout
        total_elapsed = time.time() - operation_start
        if total_elapsed >= self.total_timeout:
            logger.warning(f"[GEOCODING_TIMEOUT] Total geocoding exceeded timeout: "
                         f"{total_elapsed:.2f}s > {self.total_timeout:.2f}s")
            # Return None instead of raising for graceful degradation
            return (None, None)
        
        # All steps failed but within timeout
        logger.info(f"[GEOCODING_TIMEOUT] All geocoding steps failed for {city}, {country} "
                   f"after {total_elapsed:.2f}s")
        return (None, None)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics"""
        with self._lock:
            return {
                "total_requests": self.metrics.total_requests,
                "cache_hits": self.metrics.cache_hits,
                "cache_hit_rate": self.metrics.cache_hit_rate(),
                "city_utils_calls": self.metrics.city_utils_calls,
                "reverse_geo_calls": self.metrics.reverse_geo_calls,
                "timeouts": self.metrics.timeouts,
                "timeout_rate": self.metrics.timeout_rate(),
                "total_time": self.metrics.total_time,
                "average_time": self.metrics.average_time(),
                "cache_time": self.metrics.cache_time,
                "city_utils_time": self.metrics.city_utils_time,
                "reverse_geo_time": self.metrics.reverse_geo_time
            }
    
    def reset_metrics(self):
        """Reset all performance metrics"""
        with self._lock:
            self.metrics = GeocodingMetrics()
            logger.info("[GEOCODING_TIMEOUT] Performance metrics reset")