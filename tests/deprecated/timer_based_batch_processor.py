# timer_based_batch_processor.py - Integrates timer-based flushing with Moonshot batch processing
# Prevents batch processing bottlenecks by implementing both size and time-based triggers

import asyncio
import logging
import time
import httpx
from typing import Dict, List, Any, Optional
from batch_state_manager import BatchStateManager, BatchFlushConfig, get_batch_state_manager

logger = logging.getLogger("timer_batch_processor")

class TimerBasedBatchProcessor:
    """
    Enhanced batch processor that triggers batch processing based on both:
    1. Buffer size threshold (existing behavior)
    2. Time threshold (NEW - prevents bottlenecks for low-volume periods)
    
    This solves the batch bottleneck identified in analyze_batch_bottleneck.py
    where entries below the size threshold would wait indefinitely.
    """
    
    def __init__(self, 
                 size_threshold: int = 10,
                 time_threshold_seconds: float = 300.0,  # 5 minutes
                 enable_timer_flush: bool = True):
        
        # Configure flush behavior
        self.flush_config = BatchFlushConfig(
            size_threshold=size_threshold,
            time_threshold_seconds=time_threshold_seconds,
            enable_timer_flush=enable_timer_flush,
            flush_callback=self._on_flush_triggered
        )
        
        self.batch_state = BatchStateManager(
            max_buffer_size=1000,
            max_buffer_age_seconds=3600,
            max_result_age_seconds=7200,
            flush_config=self.flush_config
        )
        
        # Track async context for batch processing
        self._current_client: Optional[httpx.AsyncClient] = None
        self._batch_in_progress = False
        
        logger.info(f"Initialized TimerBasedBatchProcessor: "
                   f"size_threshold={size_threshold}, "
                   f"time_threshold={time_threshold_seconds}s, "
                   f"timer_enabled={enable_timer_flush}")
    
    def set_http_client(self, client: httpx.AsyncClient):
        """Set the HTTP client for batch processing"""
        self._current_client = client
    
    def _on_flush_triggered(self):
        """Callback triggered when batch should be flushed (size or time threshold)"""
        if self._batch_in_progress:
            logger.debug("Batch processing already in progress, skipping flush trigger")
            return
        
        if self._current_client is None:
            logger.warning("No HTTP client available for batch processing")
            return
        
        # Schedule async batch processing
        try:
            # Create a new event loop task if we're in an async context
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule the batch processing as a task
                loop.create_task(self._process_batch())
            else:
                # Run the batch processing directly
                asyncio.run(self._process_batch())
        except RuntimeError:
            # If no event loop is running, we can't process async batches
            logger.warning("No async event loop available for batch processing")
    
    async def _process_batch(self):
        """Process the current batch asynchronously"""
        if self._batch_in_progress:
            return
        
        self._batch_in_progress = True
        try:
            # Import the actual batch processing function
            from services.rss_processor import _process_location_batch
            
            logger.info("Timer-triggered batch processing starting...")
            results = await _process_location_batch(self._current_client)
            logger.info(f"Timer-triggered batch processing completed: {len(results)} results")
            
        except Exception as e:
            logger.error(f"Timer-triggered batch processing failed: {e}")
        finally:
            self._batch_in_progress = False
    
    def queue_entry(self, entry: Dict[str, Any], source_tag: str, uuid: str) -> bool:
        """Queue an entry for batch processing"""
        return self.batch_state.queue_entry(entry, source_tag, uuid)
    
    def get_buffer_size(self) -> int:
        """Get current buffer size"""
        return self.batch_state.get_buffer_size()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get batch processing statistics"""
        return self.batch_state.get_stats()
    
    def extract_buffer_entries(self):
        """Extract buffer entries for processing"""
        return self.batch_state.extract_buffer_entries()
    
    def store_batch_results(self, results: Dict[str, Dict[str, Any]]):
        """Store batch processing results"""
        return self.batch_state.store_batch_results(results)
    
    def get_pending_results(self) -> Dict[str, Dict[str, Any]]:
        """Get pending batch results"""
        return self.batch_state.get_pending_results()
    
    def shutdown(self):
        """Shutdown the batch processor"""
        self.batch_state.shutdown()

# Global instance for the application
_global_timer_batch_processor: Optional[TimerBasedBatchProcessor] = None

def get_timer_batch_processor() -> TimerBasedBatchProcessor:
    """Get global timer-based batch processor instance"""
    global _global_timer_batch_processor
    
    if _global_timer_batch_processor is None:
        # Get configuration from environment
        import os
        size_threshold = int(os.getenv("MOONSHOT_LOCATION_BATCH_THRESHOLD", "10"))
        time_threshold = float(os.getenv("MOONSHOT_BATCH_TIME_THRESHOLD_SECONDS", "300"))  # 5 minutes
        enable_timer = os.getenv("MOONSHOT_ENABLE_TIMER_FLUSH", "true").lower() == "true"
        
        _global_timer_batch_processor = TimerBasedBatchProcessor(
            size_threshold=size_threshold,
            time_threshold_seconds=time_threshold,
            enable_timer_flush=enable_timer
        )
        
        logger.info(f"Created global TimerBasedBatchProcessor: "
                   f"size={size_threshold}, time={time_threshold}s, timer={enable_timer}")
    
    return _global_timer_batch_processor

def reset_timer_batch_processor():
    """Reset global timer batch processor (for testing)"""
    global _global_timer_batch_processor
    
    if _global_timer_batch_processor:
        _global_timer_batch_processor.shutdown()
        _global_timer_batch_processor = None
        logger.debug("Reset global TimerBasedBatchProcessor")
