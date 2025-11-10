# batch_state_manager.py - Timer-based batch processing implementation

import threading
import time
import logging
from typing import Dict, List, Any, Optional, Callable

logger = logging.getLogger("batch_state_manager")

class BatchEntry:
    """Entry queued for batch processing"""
    def __init__(self, entry: Dict[str, Any], source_tag: str, uuid: str):
        self.entry = entry
        self.source_tag = source_tag
        self.uuid = uuid
        self.timestamp = time.time()
        self.retry_count = 0

class BatchResult:
    """Result from batch processing"""
    def __init__(self, uuid: str, result_data: Dict[str, Any]):
        self.uuid = uuid
        self.result_data = result_data
        self.processed_at = time.time()

class BatchFlushConfig:
    """Configuration for batch flush triggers"""
    def __init__(self, 
                 size_threshold: int = 10,
                 time_threshold_seconds: float = 300.0,
                 enable_timer_flush: bool = True,
                 flush_callback: Optional[Callable] = None):
        self.size_threshold = size_threshold
        self.time_threshold_seconds = time_threshold_seconds
        self.enable_timer_flush = enable_timer_flush
        self.flush_callback = flush_callback

class BatchStateManager:
    """Thread-safe batch manager with timer-based flushing"""
    
    def __init__(self, 
                 max_buffer_size: int = 1000,
                 max_buffer_age_seconds: int = 3600,
                 max_result_age_seconds: int = 7200,
                 flush_config: Optional[BatchFlushConfig] = None):
        self.max_buffer_size = max_buffer_size
        self.max_buffer_age_seconds = max_buffer_age_seconds
        self.max_result_age_seconds = max_result_age_seconds
        
        # Configure flush behavior
        self.flush_config = flush_config or BatchFlushConfig()
        
        # Thread-safe storage
        self._buffer: List[BatchEntry] = []
        self._pending_results: Dict[str, BatchResult] = {}
        self._buffer_lock = threading.RLock()
        self._results_lock = threading.RLock()
        
        # Timer-based flush tracking
        self._first_entry_time: Optional[float] = None
        self._timer_thread: Optional[threading.Thread] = None
        self._stop_timer = threading.Event()
        
        # Statistics tracking
        self._stats = {
            'total_queued': 0,
            'total_processed': 0,
            'buffer_overflows': 0,
            'cleanups_performed': 0,
            'timer_flushes': 0,
            'size_flushes': 0
        }
        self._stats_lock = threading.Lock()
        
        logger.info(f"BatchStateManager initialized: size={max_buffer_size}, timer={self.flush_config.enable_timer_flush}")
    
    def queue_entry(self, entry: Dict[str, Any], source_tag: str, uuid: str) -> bool:
        """Queue entry with timer-based flush support"""
        with self._buffer_lock:
            if len(self._buffer) >= self.max_buffer_size:
                with self._stats_lock:
                    self._stats['buffer_overflows'] += 1
                logger.warning(f"Buffer overflow: {len(self._buffer)}/{self.max_buffer_size}")
                return False
            
            batch_entry = BatchEntry(entry=entry, source_tag=source_tag, uuid=uuid)
            self._buffer.append(batch_entry)
            
            # Start timer on first entry
            if self._first_entry_time is None:
                self._first_entry_time = time.time()
                if self.flush_config.enable_timer_flush:
                    self._start_timer()
            
            with self._stats_lock:
                self._stats['total_queued'] += 1
            
            # Check size threshold
            if len(self._buffer) >= self.flush_config.size_threshold:
                logger.info(f"Size threshold reached: {len(self._buffer)}>={self.flush_config.size_threshold}")
                if self.flush_config.flush_callback:
                    self._trigger_flush("size")
            
            return True
    
    def _start_timer(self):
        """Start timer thread"""
        if self._timer_thread is not None and self._timer_thread.is_alive():
            return
        
        self._stop_timer.clear()
        self._timer_thread = threading.Thread(
            target=self._timer_worker,
            daemon=True,
            name="BatchFlushTimer"
        )
        self._timer_thread.start()
    
    def _timer_worker(self):
        """Timer worker thread"""
        while not self._stop_timer.is_set():
            self._stop_timer.wait(1.0)
            
            if self._stop_timer.is_set():
                break
            
            with self._buffer_lock:
                if not self._buffer or self._first_entry_time is None:
                    continue
                
                elapsed = time.time() - self._first_entry_time
                if elapsed >= self.flush_config.time_threshold_seconds:
                    logger.info(f"Timer threshold reached: {elapsed:.1f}s >= {self.flush_config.time_threshold_seconds}s")
                    if self.flush_config.flush_callback:
                        self._trigger_flush("timer")
                    break
    
    def _trigger_flush(self, reason: str):
        """Trigger flush callback"""
        try:
            with self._stats_lock:
                if reason == "timer":
                    self._stats['timer_flushes'] += 1
                elif reason == "size":
                    self._stats['size_flushes'] += 1
            
            self.flush_config.flush_callback()
            logger.debug(f"Flush triggered: {reason}")
        except Exception as e:
            logger.error(f"Flush callback failed: {e}")
    
    def get_buffer_size(self) -> int:
        with self._buffer_lock:
            return len(self._buffer)
    
    def extract_buffer_entries(self) -> List[BatchEntry]:
        with self._buffer_lock:
            entries = self._buffer.copy()
            self._buffer.clear()
            self._first_entry_time = None
            self._stop_timer.set()
            return entries
    
    def store_batch_results(self, results: Dict[str, Dict[str, Any]]) -> None:
        with self._results_lock:
            for uuid, result_data in results.items():
                self._pending_results[uuid] = BatchResult(uuid=uuid, result_data=result_data)
            with self._stats_lock:
                self._stats['total_processed'] += len(results)
    
    def get_pending_results(self) -> Dict[str, Dict[str, Any]]:
        with self._results_lock:
            results = {uuid: result.result_data for uuid, result in self._pending_results.items()}
            self._pending_results.clear()
            return results
    
    def get_stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            stats = self._stats.copy()
        with self._buffer_lock:
            stats['current_buffer_size'] = len(self._buffer)
            stats['first_entry_age'] = (time.time() - self._first_entry_time if self._first_entry_time else 0)
        with self._results_lock:
            stats['current_pending_results'] = len(self._pending_results)
        return stats
    
    def set_flush_callback(self, callback: Callable):
        self.flush_config.flush_callback = callback
    
    def shutdown(self):
        self._stop_timer.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=5.0)
    
    def reset(self):
        self.shutdown()
        with self._buffer_lock, self._results_lock, self._stats_lock:
            self._buffer.clear()
            self._pending_results.clear()
            self._first_entry_time = None
            self._stats = {'total_queued': 0, 'total_processed': 0, 'buffer_overflows': 0, 'cleanups_performed': 0, 'timer_flushes': 0, 'size_flushes': 0}

# Global instance
_global_batch_state_manager: Optional[BatchStateManager] = None
_manager_lock = threading.Lock()

def get_batch_state_manager() -> BatchStateManager:
    global _global_batch_state_manager
    if _global_batch_state_manager is None:
        with _manager_lock:
            if _global_batch_state_manager is None:
                _global_batch_state_manager = BatchStateManager()
                logger.info("Created global BatchStateManager")
    return _global_batch_state_manager

def reset_batch_state_manager() -> None:
    global _global_batch_state_manager
    with _manager_lock:
        if _global_batch_state_manager is not None:
            _global_batch_state_manager.reset()
