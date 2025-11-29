# batch_state_manager.py - Optimized batch processing with performance tuning

import threading
import time
import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
import json

# Enhanced logging setup
logger = logging.getLogger("batch_state_manager")

@dataclass
class BatchPerformanceMetrics:
    """Performance tracking for batch operations"""
    total_entries_processed: int = 0
    total_batches_processed: int = 0
    average_batch_size: float = 0.0
    average_processing_time_ms: float = 0.0
    memory_efficiency_score: float = 0.0
    throughput_entries_per_second: float = 0.0
    
    # Timing measurements
    last_batch_start_time: float = field(default_factory=time.time)
    last_batch_end_time: float = field(default_factory=time.time)
    
    # Memory tracking
    peak_buffer_size: int = 0
    buffer_utilization_ratio: float = 0.0

@dataclass
class BatchOptimizationConfig:
    """Dynamic optimization parameters for batch processing"""
    # Performance-optimized defaults based on typical RSS processing loads
    optimal_batch_size: int = 25  # Sweet spot for most LLM APIs
    max_batch_size: int = 50      # Hard limit to prevent memory issues
    min_batch_size: int = 5       # Minimum viable batch for efficiency
    
    # Timeout thresholds optimized for production
    fast_flush_timeout: float = 120.0   # 2 minutes for immediate processing
    standard_timeout: float = 300.0     # 5 minutes for normal loads  
    slow_timeout: float = 600.0         # 10 minutes for low activity
    emergency_timeout: float = 60.0     # 1 minute for high urgency
    
    # Dynamic adjustment parameters
    enable_dynamic_sizing: bool = True
    performance_target_ms: float = 2000.0  # Target 2s batch processing
    throughput_target_eps: float = 10.0    # Target 10 entries/second
    
    # Memory management
    memory_pressure_threshold: float = 0.85  # 85% buffer utilization
    aggressive_flush_threshold: float = 0.95  # 95% forces immediate flush

class BatchEntry:
    """Entry queued for batch processing with enhanced metadata"""
    def __init__(self, entry: Dict[str, Any], source_tag: str, uuid: str, priority: int = 0):
        self.entry = entry
        self.source_tag = source_tag
        self.uuid = uuid
        self.priority = priority  # 0=normal, 1=high, 2=urgent
        self.timestamp = time.time()
        self.retry_count = 0
        self.processing_deadline: Optional[float] = None
        self.estimated_processing_time_ms: float = 500.0  # Default estimate

class BatchResult:
    """Result from batch processing with performance metadata"""
    def __init__(self, uuid: str, result_data: Dict[str, Any], processing_time_ms: float = 0.0):
        self.uuid = uuid
        self.result_data = result_data
        self.processed_at = time.time()
        self.processing_time_ms = processing_time_ms
        self.success = True
        self.error_message: Optional[str] = None

class BatchFlushConfig:
    """Enhanced configuration for batch flush triggers with performance optimization"""
    def __init__(self, 
                 size_threshold: int = 25,                    # Optimized for LLM batch processing
                 time_threshold_seconds: float = 300.0,       # 5 minutes standard timeout
                 enable_timer_flush: bool = True,
                 enable_priority_flushing: bool = True,       # Priority-based flushing
                 enable_adaptive_sizing: bool = True,         # Dynamic batch size adjustment
                 flush_callback: Optional[Callable] = None,
                 performance_callback: Optional[Callable] = None):  # Performance monitoring callback
        
        self.size_threshold = size_threshold
        self.time_threshold_seconds = time_threshold_seconds
        self.enable_timer_flush = enable_timer_flush
        self.enable_priority_flushing = enable_priority_flushing
        self.enable_adaptive_sizing = enable_adaptive_sizing
        self.flush_callback = flush_callback
        self.performance_callback = performance_callback
        
        # Performance optimization configs
        self.optimization_config = BatchOptimizationConfig()
        
        logger.info(f"BatchFlushConfig initialized with adaptive sizing: {enable_adaptive_sizing}, "
                   f"priority flushing: {enable_priority_flushing}, size: {size_threshold}")

class BatchStateManager:
    """Optimized thread-safe batch manager with performance monitoring and dynamic tuning"""
    
    def __init__(self, 
                 max_buffer_size: int = 1000,                 # Increased for better throughput
                 max_buffer_age_seconds: int = 3600,          # 1 hour max age
                 max_result_age_seconds: int = 7200,          # 2 hours result retention
                 flush_config: Optional[BatchFlushConfig] = None,
                 enable_performance_monitoring: bool = True):
        
        self.max_buffer_size = max_buffer_size
        self.max_buffer_age_seconds = max_buffer_age_seconds
        self.max_result_age_seconds = max_result_age_seconds
        self.enable_performance_monitoring = enable_performance_monitoring
        
        # Configure flush behavior with performance optimization
        self.flush_config = flush_config or BatchFlushConfig()
        
        # Thread-safe storage with enhanced organization
        self._buffer: List[BatchEntry] = []
        self._priority_buffer: List[BatchEntry] = []  # High priority entries
        self._pending_results: Dict[str, BatchResult] = {}
        self._buffer_lock = threading.RLock()
        self._results_lock = threading.RLock()
        
        # Timer-based flush tracking with performance optimization
        self._first_entry_time: Optional[float] = None
        self._timer_thread: Optional[threading.Thread] = None
        self._stop_timer = threading.Event()
        
        # Performance monitoring
        self._performance_metrics = BatchPerformanceMetrics()
        self._performance_lock = threading.Lock()
        
        # Enhanced statistics tracking
        self._stats = {
            'total_queued': 0,
            'total_processed': 0,
            'buffer_overflows': 0,
            'priority_overrides': 0,
            'cleanups_performed': 0,
            'timer_flushes': 0,
            'size_flushes': 0,
            'priority_flushes': 0,
            'adaptive_resizes': 0,
            'performance_optimizations': 0,
            'memory_pressure_events': 0,
            'emergency_flushes': 0,
            'last_cleanup_time': 0.0,
            'uptime_seconds': time.time()
        }
        self._stats_lock = threading.Lock()
        
        # Dynamic optimization state
        self._last_optimization_time = time.time()
        self._optimization_interval = 60.0  # Optimize every minute
        
        logger.info(f"BatchStateManager initialized with enhanced performance monitoring: "
                   f"max_size={max_buffer_size}, monitoring={enable_performance_monitoring}, "
                   f"adaptive_sizing={self.flush_config.enable_adaptive_sizing}")
        
        # Start performance monitoring if enabled
        if self.enable_performance_monitoring:
            self._start_performance_monitoring()
    
    def queue_entry(self, entry: Dict[str, Any], source_tag: str, uuid: str, priority: int = 0) -> bool:
        """Queue entry with optimized performance monitoring and dynamic threshold management"""
        start_time = time.time()
        
        try:
            with self._buffer_lock:
                # Check memory pressure and handle overflow intelligently
                total_entries = len(self._buffer) + len(self._priority_buffer)
                memory_pressure = total_entries / self.max_buffer_size
                
                if total_entries >= self.max_buffer_size:
                    with self._stats_lock:
                        self._stats['buffer_overflows'] += 1
                        self._stats['memory_pressure_events'] += 1
                    
                    logger.warning(f"Buffer overflow detected: {total_entries}/{self.max_buffer_size} "
                                 f"(pressure: {memory_pressure:.2%}). Priority: {priority}")
                    
                    # Emergency flush for high priority items
                    if priority >= 1:
                        logger.info("Triggering emergency flush for high-priority entry")
                        self._trigger_emergency_flush()
                        with self._stats_lock:
                            self._stats['emergency_flushes'] += 1
                    else:
                        return False
                
                # Create enhanced batch entry
                batch_entry = BatchEntry(entry=entry, source_tag=source_tag, uuid=uuid, priority=priority)
                
                # Set processing deadline based on priority
                if priority >= 2:  # Urgent
                    batch_entry.processing_deadline = time.time() + self.flush_config.optimization_config.emergency_timeout
                elif priority >= 1:  # High
                    batch_entry.processing_deadline = time.time() + self.flush_config.optimization_config.fast_flush_timeout
                else:  # Normal
                    batch_entry.processing_deadline = time.time() + self.flush_config.optimization_config.standard_timeout
                
                # Queue in appropriate buffer based on priority
                if priority >= 1 and self.flush_config.enable_priority_flushing:
                    self._priority_buffer.append(batch_entry)
                    logger.debug(f"Queued high-priority entry: {uuid} (priority: {priority})")
                    with self._stats_lock:
                        self._stats['priority_overrides'] += 1
                else:
                    self._buffer.append(batch_entry)
                    logger.debug(f"Queued normal entry: {uuid}")
                
                # Start timer on first entry
                if self._first_entry_time is None:
                    self._first_entry_time = time.time()
                    if self.flush_config.enable_timer_flush:
                        self._start_timer()
                    logger.debug("Started batch timer for first entry")
                
                # Update performance metrics
                with self._performance_lock:
                    self._performance_metrics.peak_buffer_size = max(
                        self._performance_metrics.peak_buffer_size, 
                        total_entries + 1
                    )
                    self._performance_metrics.buffer_utilization_ratio = (total_entries + 1) / self.max_buffer_size
                
                with self._stats_lock:
                    self._stats['total_queued'] += 1
                
                # Check flush conditions with optimized thresholds
                self._check_flush_conditions(memory_pressure, priority)
                
                # Adaptive optimization check
                self._perform_adaptive_optimization()
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to queue entry {uuid}: {e}", exc_info=True)
            return False
        finally:
            # Track queueing performance
            queue_time_ms = (time.time() - start_time) * 1000
            if queue_time_ms > 10.0:  # Log if queueing takes > 10ms
                logger.warning(f"Slow queue operation: {queue_time_ms:.1f}ms for entry {uuid}")
    
    def _check_flush_conditions(self, memory_pressure: float, entry_priority: int) -> None:
        """Intelligent flush condition checking with performance optimization"""
        total_entries = len(self._buffer) + len(self._priority_buffer)
        
        # Priority-based immediate flush
        if (entry_priority >= 2 and self.flush_config.enable_priority_flushing):
            logger.info(f"Triggering urgent priority flush for {total_entries} entries")
            self._trigger_flush("urgent_priority")
            return
        
        # Memory pressure-based flush  
        if memory_pressure >= self.flush_config.optimization_config.aggressive_flush_threshold:
            logger.warning(f"Memory pressure critical: {memory_pressure:.2%} >= {self.flush_config.optimization_config.aggressive_flush_threshold:.2%}")
            self._trigger_flush("memory_pressure")
            return
        
        # Adaptive size threshold
        current_threshold = self._get_adaptive_size_threshold()
        
        # Size-based flush with adaptive threshold
        if total_entries >= current_threshold:
            logger.info(f"Size threshold reached: {total_entries} >= {current_threshold} (adaptive)")
            self._trigger_flush("adaptive_size")
            return
        
        # High priority buffer flush
        if len(self._priority_buffer) >= 5:  # Flush priority buffer more aggressively
            logger.info(f"Priority buffer size reached: {len(self._priority_buffer)} >= 5")
            self._trigger_flush("priority_size")
            return
    
    def _get_adaptive_size_threshold(self) -> int:
        """Calculate adaptive size threshold based on performance metrics"""
        if not self.flush_config.enable_adaptive_sizing:
            return self.flush_config.size_threshold
        
        with self._performance_lock:
            # Adjust based on recent performance
            if self._performance_metrics.average_processing_time_ms > self.flush_config.optimization_config.performance_target_ms:
                # Processing is slow, use smaller batches
                adaptive_threshold = max(
                    self.flush_config.optimization_config.min_batch_size,
                    int(self.flush_config.size_threshold * 0.7)
                )
                logger.debug(f"Slow processing detected ({self._performance_metrics.average_processing_time_ms:.1f}ms), "
                           f"reducing batch size to {adaptive_threshold}")
            else:
                # Processing is fast, can use larger batches
                adaptive_threshold = min(
                    self.flush_config.optimization_config.optimal_batch_size,
                    int(self.flush_config.size_threshold * 1.2)
                )
        
        return adaptive_threshold
    
    def _start_timer(self):
        """Start optimized timer thread with adaptive scheduling"""
        if self._timer_thread is not None and self._timer_thread.is_alive():
            return
        
        self._stop_timer.clear()
        self._timer_thread = threading.Thread(
            target=self._optimized_timer_worker,
            daemon=True,
            name="BatchFlushTimer-Optimized"
        )
        self._timer_thread.start()
        logger.debug("Started optimized batch timer thread")
    
    def _optimized_timer_worker(self):
        """Enhanced timer worker with dynamic timeout adjustment"""
        check_interval = 1.0  # Check every second
        
        while not self._stop_timer.is_set():
            try:
                self._stop_timer.wait(check_interval)
                
                if self._stop_timer.is_set():
                    break
                
                with self._buffer_lock:
                    if not self._buffer and not self._priority_buffer:
                        continue
                    
                    if self._first_entry_time is None:
                        continue
                    
                    current_time = time.time()
                    elapsed = current_time - self._first_entry_time
                    
                    # Check for deadline-based flushes (urgent entries)
                    urgent_deadline_reached = self._check_urgent_deadlines(current_time)
                    
                    # Adaptive timeout based on buffer state and priority
                    timeout_threshold = self._calculate_adaptive_timeout()
                    
                    should_flush = (
                        elapsed >= timeout_threshold or 
                        urgent_deadline_reached or
                        self._has_stale_entries(current_time)
                    )
                    
                    if should_flush:
                        flush_reason = (
                            "urgent_deadline" if urgent_deadline_reached else
                            "stale_entries" if self._has_stale_entries(current_time) else
                            "adaptive_timer"
                        )
                        
                        logger.info(f"Timer flush triggered: elapsed={elapsed:.1f}s, "
                                  f"threshold={timeout_threshold:.1f}s, reason={flush_reason}")
                        
                        if self.flush_config.flush_callback:
                            self._trigger_flush(flush_reason)
                        break
                        
            except Exception as e:
                logger.error(f"Timer worker error: {e}", exc_info=True)
                time.sleep(5.0)  # Brief pause on error
    
    def _check_urgent_deadlines(self, current_time: float) -> bool:
        """Check if any urgent entries have reached their deadline"""
        for entry in self._priority_buffer + self._buffer:
            if (entry.processing_deadline and 
                current_time >= entry.processing_deadline and 
                entry.priority >= 1):
                logger.warning(f"Urgent entry {entry.uuid} deadline reached: "
                             f"{current_time - entry.processing_deadline:.1f}s overdue")
                return True
        return False
    
    def _has_stale_entries(self, current_time: float) -> bool:
        """Check for entries that have exceeded max age"""
        for entry in self._buffer + self._priority_buffer:
            age = current_time - entry.timestamp
            if age > self.max_buffer_age_seconds:
                logger.warning(f"Stale entry detected: {entry.uuid} age={age:.1f}s > {self.max_buffer_age_seconds}s")
                return True
        return False
    
    def _calculate_adaptive_timeout(self) -> float:
        """Calculate adaptive timeout based on buffer state and performance"""
        base_timeout = self.flush_config.time_threshold_seconds
        
        # Shorter timeout for priority entries
        if self._priority_buffer:
            base_timeout = min(base_timeout, self.flush_config.optimization_config.fast_flush_timeout)
        
        # Adjust based on buffer utilization
        total_entries = len(self._buffer) + len(self._priority_buffer)
        utilization = total_entries / self.max_buffer_size
        
        if utilization > 0.8:  # High utilization = faster flush
            base_timeout *= 0.5
        elif utilization < 0.2:  # Low utilization = can wait longer
            base_timeout *= 1.5
        
        # Performance-based adjustment
        with self._performance_lock:
            if (self._performance_metrics.average_processing_time_ms > 
                self.flush_config.optimization_config.performance_target_ms):
                base_timeout *= 0.8  # Flush sooner if processing is slow
        
        return max(30.0, min(base_timeout, 900.0))  # Clamp between 30s and 15min
    
    def _trigger_emergency_flush(self):
        """Emergency flush for critical situations"""
        logger.warning("Emergency flush triggered due to buffer overflow with priority entry")
        if self.flush_config.flush_callback:
            try:
                self.flush_config.flush_callback()
            except Exception as e:
                logger.error(f"Emergency flush callback failed: {e}", exc_info=True)
    
    def _start_performance_monitoring(self):
        """Start background performance monitoring"""
        monitoring_thread = threading.Thread(
            target=self._performance_monitor_worker,
            daemon=True,
            name="BatchPerformanceMonitor"
        )
        monitoring_thread.start()
        logger.info("Started performance monitoring thread")
    
    def _performance_monitor_worker(self):
        """Background performance monitoring and optimization"""
        while True:
            try:
                time.sleep(30.0)  # Monitor every 30 seconds
                
                # Collect and log performance metrics
                self._update_performance_metrics()
                self._log_performance_summary()
                self._cleanup_stale_results()
                
            except Exception as e:
                logger.error(f"Performance monitoring error: {e}", exc_info=True)
    
    def _update_performance_metrics(self):
        """Update performance metrics based on current state"""
        with self._performance_lock, self._stats_lock:
            current_time = time.time()
            uptime = current_time - self._stats['uptime_seconds']
            
            if self._stats['total_processed'] > 0 and self._performance_metrics.total_batches_processed > 0:
                self._performance_metrics.average_batch_size = (
                    self._stats['total_processed'] / self._performance_metrics.total_batches_processed
                )
                self._performance_metrics.throughput_entries_per_second = (
                    self._stats['total_processed'] / max(uptime, 1.0)
                )
            
            # Calculate memory efficiency
            buffer_utilization = (len(self._buffer) + len(self._priority_buffer)) / self.max_buffer_size
            self._performance_metrics.buffer_utilization_ratio = buffer_utilization
            self._performance_metrics.memory_efficiency_score = 1.0 - (
                self._stats['buffer_overflows'] / max(self._stats['total_queued'], 1)
            )
    
    def _log_performance_summary(self):
        """Log comprehensive performance summary"""
        with self._performance_lock, self._stats_lock:
            buffer_size = len(self._buffer) + len(self._priority_buffer)
            
            logger.info(f"🚀 Batch Performance Summary: "
                       f"buffer={buffer_size}/{self.max_buffer_size} "
                       f"({self._performance_metrics.buffer_utilization_ratio:.1%}), "
                       f"throughput={self._performance_metrics.throughput_entries_per_second:.1f} eps, "
                       f"avg_batch={self._performance_metrics.average_batch_size:.1f}, "
                       f"processing={self._performance_metrics.average_processing_time_ms:.1f}ms, "
                       f"efficiency={self._performance_metrics.memory_efficiency_score:.2%}")
            
            # Performance callback for external monitoring
            if self.flush_config.performance_callback:
                try:
                    self.flush_config.performance_callback(self._performance_metrics)
                except Exception as e:
                    logger.debug(f"Performance callback error: {e}")
    
    def _cleanup_stale_results(self):
        """Clean up old results to prevent memory leaks"""
        current_time = time.time()
        cleaned_count = 0
        
        with self._results_lock:
            stale_uuids = [
                uuid for uuid, result in self._pending_results.items()
                if current_time - result.processed_at > self.max_result_age_seconds
            ]
            
            for uuid in stale_uuids:
                del self._pending_results[uuid]
                cleaned_count += 1
        
        if cleaned_count > 0:
            with self._stats_lock:
                self._stats['cleanups_performed'] += 1
                self._stats['last_cleanup_time'] = current_time
            logger.debug(f"Cleaned up {cleaned_count} stale results")
    
    def _perform_adaptive_optimization(self):
        """Perform adaptive optimization based on performance data"""
        current_time = time.time()
        
        if (current_time - self._last_optimization_time) < self._optimization_interval:
            return
        
        self._last_optimization_time = current_time
        
        with self._performance_lock:
            # Optimize based on throughput
            if (self._performance_metrics.throughput_entries_per_second < 
                self.flush_config.optimization_config.throughput_target_eps):
                
                # Low throughput - reduce batch size for faster processing
                if self.flush_config.enable_adaptive_sizing:
                    old_threshold = self.flush_config.size_threshold
                    self.flush_config.size_threshold = max(
                        self.flush_config.optimization_config.min_batch_size,
                        int(self.flush_config.size_threshold * 0.9)
                    )
                    
                    if self.flush_config.size_threshold != old_threshold:
                        with self._stats_lock:
                            self._stats['adaptive_resizes'] += 1
                            self._stats['performance_optimizations'] += 1
                        
                        logger.info(f"Adaptive optimization: reduced batch size from {old_threshold} "
                                   f"to {self.flush_config.size_threshold} due to low throughput "
                                   f"({self._performance_metrics.throughput_entries_per_second:.1f} eps)")
    
    def _trigger_flush(self, reason: str):
        """Enhanced flush trigger with performance tracking"""
        flush_start_time = time.time()
        
        try:
            with self._stats_lock:
                if reason == "timer" or reason == "adaptive_timer":
                    self._stats['timer_flushes'] += 1
                elif "size" in reason:
                    self._stats['size_flushes'] += 1
                elif "priority" in reason:
                    self._stats['priority_flushes'] += 1
                elif reason == "memory_pressure":
                    self._stats['memory_pressure_events'] += 1
                elif reason == "urgent_deadline":
                    self._stats['emergency_flushes'] += 1
            
            # Call the flush callback
            if self.flush_config.flush_callback:
                self.flush_config.flush_callback()
            
            # Track flush performance
            flush_time_ms = (time.time() - flush_start_time) * 1000
            
            with self._performance_lock:
                self._performance_metrics.total_batches_processed += 1
                # Update average processing time with exponential moving average
                alpha = 0.1
                self._performance_metrics.average_processing_time_ms = (
                    alpha * flush_time_ms + 
                    (1 - alpha) * self._performance_metrics.average_processing_time_ms
                )
            
            logger.debug(f"Flush completed: reason={reason}, duration={flush_time_ms:.1f}ms")
            
        except Exception as e:
            logger.error(f"Flush callback failed (reason: {reason}): {e}", exc_info=True)
    
    def get_buffer_size(self) -> int:
        """Get total buffer size including priority buffer"""
        with self._buffer_lock:
            return len(self._buffer) + len(self._priority_buffer)
    
    def get_priority_buffer_size(self) -> int:
        """Get priority buffer size specifically"""
        with self._buffer_lock:
            return len(self._priority_buffer)
    
    def extract_buffer_entries(self) -> List[BatchEntry]:
        """Extract all entries with priority-based ordering"""
        with self._buffer_lock:
            # Combine buffers with priority first
            all_entries = self._priority_buffer + self._buffer
            
            # Sort by priority (descending) then by timestamp (ascending)
            all_entries.sort(key=lambda x: (-x.priority, x.timestamp))
            
            # Clear buffers and reset timer
            self._buffer.clear()
            self._priority_buffer.clear()
            self._first_entry_time = None
            self._stop_timer.set()
            
            logger.info(f"Extracted {len(all_entries)} entries for processing "
                       f"(priority: {len([e for e in all_entries if e.priority >= 1])})")
            
            return all_entries
    
    def store_batch_results(self, results: Dict[str, Dict[str, Any]], processing_time_ms: float = 0.0) -> None:
        """Store batch results with performance tracking"""
        with self._results_lock:
            for uuid, result_data in results.items():
                batch_result = BatchResult(
                    uuid=uuid, 
                    result_data=result_data, 
                    processing_time_ms=processing_time_ms
                )
                self._pending_results[uuid] = batch_result
            
            with self._stats_lock:
                self._stats['total_processed'] += len(results)
            
            # Update performance metrics
            with self._performance_lock:
                self._performance_metrics.total_entries_processed += len(results)
                if processing_time_ms > 0:
                    # Update processing time with exponential moving average
                    alpha = 0.2
                    self._performance_metrics.average_processing_time_ms = (
                        alpha * processing_time_ms + 
                        (1 - alpha) * self._performance_metrics.average_processing_time_ms
                    )
            
            logger.debug(f"Stored {len(results)} batch results, processing time: {processing_time_ms:.1f}ms")
    
    def get_pending_results(self) -> Dict[str, Dict[str, Any]]:
        """Get and clear pending results"""
        with self._results_lock:
            results = {uuid: result.result_data for uuid, result in self._pending_results.items()}
            result_count = len(self._pending_results)
            self._pending_results.clear()
            
            if result_count > 0:
                logger.debug(f"Retrieved {result_count} pending results")
            
            return results
    
    def get_performance_metrics(self) -> BatchPerformanceMetrics:
        """Get current performance metrics"""
        with self._performance_lock:
            return self._performance_metrics
    
    def get_detailed_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics including performance data"""
        with self._stats_lock:
            stats = self._stats.copy()
        
        with self._buffer_lock:
            stats['current_buffer_size'] = len(self._buffer)
            stats['current_priority_buffer_size'] = len(self._priority_buffer)
            stats['total_buffered_entries'] = len(self._buffer) + len(self._priority_buffer)
            stats['first_entry_age'] = (time.time() - self._first_entry_time if self._first_entry_time else 0)
            
            # Buffer composition analysis
            if self._buffer or self._priority_buffer:
                all_entries = self._buffer + self._priority_buffer
                stats['buffer_priority_distribution'] = {
                    'normal': len([e for e in all_entries if e.priority == 0]),
                    'high': len([e for e in all_entries if e.priority == 1]),
                    'urgent': len([e for e in all_entries if e.priority >= 2])
                }
                
                # Age analysis
                current_time = time.time()
                ages = [current_time - entry.timestamp for entry in all_entries]
                if ages:
                    stats['buffer_age_stats'] = {
                        'min_age_seconds': min(ages),
                        'max_age_seconds': max(ages),
                        'avg_age_seconds': sum(ages) / len(ages)
                    }
        
        with self._results_lock:
            stats['current_pending_results'] = len(self._pending_results)
        
        # Performance metrics
        with self._performance_lock:
            stats['performance'] = {
                'throughput_eps': self._performance_metrics.throughput_entries_per_second,
                'avg_processing_time_ms': self._performance_metrics.average_processing_time_ms,
                'avg_batch_size': self._performance_metrics.average_batch_size,
                'memory_efficiency': self._performance_metrics.memory_efficiency_score,
                'buffer_utilization': self._performance_metrics.buffer_utilization_ratio,
                'peak_buffer_size': self._performance_metrics.peak_buffer_size
            }
        
        # System health indicators
        uptime = time.time() - stats['uptime_seconds']
        stats['system_health'] = {
            'uptime_hours': uptime / 3600,
            'overflow_rate': stats['buffer_overflows'] / max(stats['total_queued'], 1),
            'processing_efficiency': stats['total_processed'] / max(stats['total_queued'], 1),
            'adaptive_optimization_count': stats.get('adaptive_resizes', 0),
            'emergency_intervention_rate': stats.get('emergency_flushes', 0) / max(stats['total_processed'], 1)
        }
        
        return stats
    
    def get_stats(self) -> Dict[str, Any]:
        """Get basic statistics (backward compatibility)"""
        return self.get_detailed_stats()
    
    def set_flush_callback(self, callback: Callable):
        """Set flush callback"""
        self.flush_config.flush_callback = callback
        logger.debug("Updated flush callback")
    
    def set_performance_callback(self, callback: Callable):
        """Set performance monitoring callback"""
        self.flush_config.performance_callback = callback
        logger.debug("Updated performance callback")
    
    def optimize_configuration(self, target_throughput: float = None, target_latency_ms: float = None):
        """Dynamically optimize configuration based on performance targets"""
        if target_throughput:
            self.flush_config.optimization_config.throughput_target_eps = target_throughput
        if target_latency_ms:
            self.flush_config.optimization_config.performance_target_ms = target_latency_ms
        
        logger.info(f"Updated performance targets: throughput={target_throughput} eps, "
                   f"latency={target_latency_ms}ms")
        
        with self._stats_lock:
            self._stats['performance_optimizations'] += 1
    
    def shutdown(self):
        """Graceful shutdown with cleanup"""
        logger.info("Initiating BatchStateManager shutdown...")
        
        # Stop timer
        self._stop_timer.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=5.0)
            if self._timer_thread.is_alive():
                logger.warning("Timer thread did not shutdown gracefully")
        
        # Final performance summary
        self._log_performance_summary()
        
        logger.info("BatchStateManager shutdown completed")
    
    def reset(self):
        """Reset state with enhanced cleanup"""
        logger.info("Resetting BatchStateManager state...")
        
        self.shutdown()
        
        with self._buffer_lock, self._results_lock, self._stats_lock, self._performance_lock:
            # Clear all data structures
            self._buffer.clear()
            self._priority_buffer.clear()
            self._pending_results.clear()
            self._first_entry_time = None
            
            # Reset stats
            self._stats = {
                'total_queued': 0,
                'total_processed': 0,
                'buffer_overflows': 0,
                'priority_overrides': 0,
                'cleanups_performed': 0,
                'timer_flushes': 0,
                'size_flushes': 0,
                'priority_flushes': 0,
                'adaptive_resizes': 0,
                'performance_optimizations': 0,
                'memory_pressure_events': 0,
                'emergency_flushes': 0,
                'last_cleanup_time': 0.0,
                'uptime_seconds': time.time()
            }
            
            # Reset performance metrics
            self._performance_metrics = BatchPerformanceMetrics()
            
        logger.info("BatchStateManager reset completed")

# Optimized global instance with performance monitoring
_global_batch_state_manager: Optional[BatchStateManager] = None
_manager_lock = threading.Lock()

def get_batch_state_manager() -> BatchStateManager:
    """Get or create global BatchStateManager with optimal configuration"""
    global _global_batch_state_manager
    if _global_batch_state_manager is None:
        with _manager_lock:
            if _global_batch_state_manager is None:
                # Create with optimized settings for production
                optimized_flush_config = BatchFlushConfig(
                    size_threshold=25,  # Optimal for LLM processing
                    time_threshold_seconds=300.0,  # 5 minutes
                    enable_timer_flush=True,
                    enable_priority_flushing=True,
                    enable_adaptive_sizing=True
                )
                
                _global_batch_state_manager = BatchStateManager(
                    max_buffer_size=1000,
                    max_buffer_age_seconds=3600,  # 1 hour
                    max_result_age_seconds=7200,  # 2 hours
                    flush_config=optimized_flush_config,
                    enable_performance_monitoring=True
                )
                logger.info("Created optimized global BatchStateManager with performance monitoring")
    return _global_batch_state_manager

def reset_batch_state_manager() -> None:
    """Reset global BatchStateManager"""
    global _global_batch_state_manager
    with _manager_lock:
        if _global_batch_state_manager is not None:
            _global_batch_state_manager.reset()
            logger.info("Reset global BatchStateManager")

def get_batch_performance_report() -> Dict[str, Any]:
    """Get comprehensive performance report from global manager"""
    manager = get_batch_state_manager()
    return {
        'detailed_stats': manager.get_detailed_stats(),
        'performance_metrics': manager.get_performance_metrics(),
        'configuration': {
            'max_buffer_size': manager.max_buffer_size,
            'size_threshold': manager.flush_config.size_threshold,
            'time_threshold': manager.flush_config.time_threshold_seconds,
            'adaptive_sizing_enabled': manager.flush_config.enable_adaptive_sizing,
            'priority_flushing_enabled': manager.flush_config.enable_priority_flushing,
            'performance_monitoring_enabled': manager.enable_performance_monitoring,
        },
        'optimization_config': {
            'optimal_batch_size': manager.flush_config.optimization_config.optimal_batch_size,
            'performance_target_ms': manager.flush_config.optimization_config.performance_target_ms,
            'throughput_target_eps': manager.flush_config.optimization_config.throughput_target_eps,
        },
        'timestamp': time.time()
    }

def log_batch_performance_summary():
    """Log a comprehensive performance summary"""
    try:
        report = get_batch_performance_report()
        stats = report['detailed_stats']
        perf = report['performance_metrics']
        
        logger.info("="*60)
        logger.info("📊 BATCH PROCESSING PERFORMANCE REPORT")
        logger.info("="*60)
        logger.info(f"🚀 Throughput: {perf.throughput_entries_per_second:.2f} entries/sec")
        logger.info(f"⏱️  Avg Processing: {perf.average_processing_time_ms:.1f}ms")
        logger.info(f"📦 Avg Batch Size: {perf.average_batch_size:.1f} entries")
        logger.info(f"💾 Memory Efficiency: {perf.memory_efficiency_score:.1%}")
        logger.info(f"📊 Buffer Utilization: {perf.buffer_utilization_ratio:.1%}")
        logger.info(f"📈 Total Processed: {stats['total_processed']:,} entries")
        logger.info(f"⚠️  Buffer Overflows: {stats['buffer_overflows']} ({stats['system_health']['overflow_rate']:.2%})")
        logger.info(f"🔄 Adaptive Resizes: {stats.get('adaptive_resizes', 0)}")
        logger.info(f"🚨 Emergency Flushes: {stats.get('emergency_flushes', 0)}")
        logger.info(f"⏰ System Uptime: {stats['system_health']['uptime_hours']:.1f} hours")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Failed to generate performance summary: {e}", exc_info=True)
