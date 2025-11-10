# batch_state_manager.py — Thread-safe batch processing state management
# Replaces function attributes anti-pattern with proper state management

import threading
import time
import logging
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("batch_state_manager")

@dataclass
class BatchEntry:
    """Represents a single entry queued for batch processing"""
    entry: Dict[str, Any]
    source_tag: str
    uuid: str
    timestamp: float = field(default_factory=time.time)

@dataclass 
class BatchResult:
    """Result from batch processing"""
    uuid: str
    result_data: Dict[str, Any]
    processed_at: float = field(default_factory=time.time)

class BatchStateManager:
    """
    Thread-safe manager for batch processing state.
    
    Eliminates the anti-pattern of using function attributes 
    (_build_alert_from_entry._pending_batch_results) for global state.
    
    Features:
    - Thread-safe operations
    - Automatic cleanup of stale entries  
    - Clear data flow and boundaries
    - Testable and mockable
    - Memory leak prevention
    """
    
    def __init__(self, 
                 max_buffer_size: int = 1000,
                 max_buffer_age_seconds: int = 3600,
                 max_result_age_seconds: int = 7200):
        self.max_buffer_size = max_buffer_size
        self.max_buffer_age_seconds = max_buffer_age_seconds
        self.max_result_age_seconds = max_result_age_seconds
        
        # Thread-safe storage
        self._buffer: List[BatchEntry] = []
        self._pending_results: Dict[str, BatchResult] = {}
        self._buffer_lock = threading.RLock()  # Reentrant lock for nested access
        self._results_lock = threading.RLock()
        
        # Statistics tracking
        self._stats = {
            'total_queued': 0,
            'total_processed': 0,
            'buffer_overflows': 0,
            'cleanups_performed': 0
        }
        self._stats_lock = threading.Lock()
        
        logger.info(f"Initialized BatchStateManager: buffer_size={max_buffer_size}, "
                   f"buffer_age={max_buffer_age_seconds}s, result_age={max_result_age_seconds}s")
    
    def queue_entry(self, entry: Dict[str, Any], source_tag: str, uuid: str) -> bool:
        """
        Queue an entry for batch processing.
        
        Returns:
            True if queued successfully, False if buffer is full
        """
        with self._buffer_lock:
            # Cleanup stale entries first
            self._cleanup_stale_buffer_entries()
            
            # Check buffer size limit
            if len(self._buffer) >= self.max_buffer_size:
                with self._stats_lock:
                    self._stats['buffer_overflows'] += 1
                logger.warning(f"Buffer overflow: {len(self._buffer)}/{self.max_buffer_size}")
                return False
            
            # Add entry
            batch_entry = BatchEntry(entry=entry, source_tag=source_tag, uuid=uuid)
            self._buffer.append(batch_entry)
            
            with self._stats_lock:
                self._stats['total_queued'] += 1
            
            logger.debug(f"Queued entry {uuid}: buffer_size={len(self._buffer)}")
            return True
    
    def get_buffer_size(self) -> int:
        """Get current buffer size (thread-safe)"""
        with self._buffer_lock:
            return len(self._buffer)
    
    def extract_buffer_entries(self) -> List[BatchEntry]:
        """
        Extract all buffer entries for processing.
        Thread-safe operation that clears the buffer.
        """
        with self._buffer_lock:
            entries = self._buffer.copy()
            self._buffer.clear()
            logger.debug(f"Extracted {len(entries)} entries for batch processing")
            return entries
    
    def store_batch_results(self, results: Dict[str, Dict[str, Any]]) -> None:
        """
        Store results from batch processing.
        
        Args:
            results: Dict mapping UUIDs to result data
        """
        with self._results_lock:
            # Cleanup old results first
            self._cleanup_stale_results()
            
            # Store new results
            for uuid, result_data in results.items():
                self._pending_results[uuid] = BatchResult(
                    uuid=uuid,
                    result_data=result_data
                )
            
            with self._stats_lock:
                self._stats['total_processed'] += len(results)
            
            logger.debug(f"Stored {len(results)} batch results: "
                        f"total_pending={len(self._pending_results)}")
    
    def get_pending_results(self) -> Dict[str, Dict[str, Any]]:
        """
        Get and clear all pending results.
        Thread-safe operation for consuming results.
        """
        with self._results_lock:
            # Extract results
            results = {
                uuid: result.result_data 
                for uuid, result in self._pending_results.items()
            }
            
            # Clear pending results
            self._pending_results.clear()
            
            logger.debug(f"Retrieved and cleared {len(results)} pending results")
            return results
    
    def _cleanup_stale_buffer_entries(self) -> None:
        """Remove entries older than max_buffer_age_seconds"""
        if not self._buffer:
            return
            
        cutoff_time = time.time() - self.max_buffer_age_seconds
        original_size = len(self._buffer)
        
        # Filter out stale entries
        self._buffer = [entry for entry in self._buffer if entry.timestamp > cutoff_time]
        
        removed = original_size - len(self._buffer)
        if removed > 0:
            logger.info(f"Cleaned up {removed} stale buffer entries (age > {self.max_buffer_age_seconds}s)")
            with self._stats_lock:
                self._stats['cleanups_performed'] += 1
    
    def _cleanup_stale_results(self) -> None:
        """Remove results older than max_result_age_seconds"""
        if not self._pending_results:
            return
            
        cutoff_time = time.time() - self.max_result_age_seconds
        original_size = len(self._pending_results)
        
        # Filter out stale results
        self._pending_results = {
            uuid: result for uuid, result in self._pending_results.items()
            if result.processed_at > cutoff_time
        }
        
        removed = original_size - len(self._pending_results)
        if removed > 0:
            logger.info(f"Cleaned up {removed} stale result entries (age > {self.max_result_age_seconds}s)")
    
    def force_cleanup(self) -> None:
        """Force cleanup of all stale entries (for testing/maintenance)"""
        with self._buffer_lock:
            self._cleanup_stale_buffer_entries()
        
        with self._results_lock:
            self._cleanup_stale_results()
            
        logger.info("Forced cleanup completed")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        with self._stats_lock:
            stats = self._stats.copy()
        
        with self._buffer_lock:
            stats['current_buffer_size'] = len(self._buffer)
        
        with self._results_lock:
            stats['current_pending_results'] = len(self._pending_results)
        
        return stats
    
    def reset(self) -> None:
        """Reset all state (for testing)"""
        with self._buffer_lock, self._results_lock, self._stats_lock:
            self._buffer.clear()
            self._pending_results.clear()
            self._stats = {
                'total_queued': 0,
                'total_processed': 0,
                'buffer_overflows': 0,
                'cleanups_performed': 0
            }
            logger.debug("BatchStateManager reset completed")

# Global instance (properly initialized, not as function attribute)
_global_batch_state_manager: Optional[BatchStateManager] = None
_manager_lock = threading.Lock()

def get_batch_state_manager() -> BatchStateManager:
    """
    Get the global batch state manager instance.
    Thread-safe singleton pattern.
    """
    global _global_batch_state_manager
    
    if _global_batch_state_manager is None:
        with _manager_lock:
            # Double-check locking pattern
            if _global_batch_state_manager is None:
                _global_batch_state_manager = BatchStateManager()
                logger.info("Created global BatchStateManager instance")
    
    return _global_batch_state_manager

def reset_batch_state_manager() -> None:
    """Reset the global batch state manager (for testing)"""
    global _global_batch_state_manager
    
    with _manager_lock:
        if _global_batch_state_manager is not None:
            _global_batch_state_manager.reset()
            logger.debug("Reset global BatchStateManager")
