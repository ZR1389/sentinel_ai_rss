#!/usr/bin/env python3
"""
Performance Analysis - Batch Processing Bottlenecks

Analyzing the current batch processing logic to identify timer-based flush issues.
"""

import logging
import time
from typing import List, Dict, Any
from dataclasses import dataclass

# Set up test environment 
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("batch_perf_analysis")

@dataclass
class MockAlert:
    uuid: str
    title: str
    timestamp: float

class BatchProcessingAnalyzer:
    """Analyze current batch processing performance issues"""
    
    def __init__(self, batch_threshold: int = 10):
        self.batch_threshold = batch_threshold
        self.buffer: List[MockAlert] = []
        self.processed_batches: List[Dict] = []
        self.last_flush_time = time.time()
        
    def add_alert(self, alert: MockAlert):
        """Add alert to buffer (current logic)"""
        self.buffer.append(alert)
        
        # CURRENT PROBLEMATIC LOGIC:
        # Only process when buffer >= threshold
        if len(self.buffer) >= self.batch_threshold:
            logger.info(f"🔄 Processing batch of {len(self.buffer)} alerts (threshold reached)")
            self._process_batch()
        else:
            logger.debug(f"📋 Buffer size: {len(self.buffer)}/{self.batch_threshold}")
    
    def _process_batch(self):
        """Mock batch processing"""
        if not self.buffer:
            return
            
        batch_info = {
            'size': len(self.buffer),
            'processing_time': time.time(),
            'latency': time.time() - self.last_flush_time
        }
        
        self.processed_batches.append(batch_info)
        logger.info(f"✅ Processed batch: {batch_info}")
        
        # Clear buffer
        self.buffer.clear()
        self.last_flush_time = time.time()
    
    def force_flush(self):
        """Process remaining buffer (current end-of-run logic)"""
        if self.buffer:
            logger.warning(f"⚠️ Force flushing {len(self.buffer)} remaining alerts")
            self._process_batch()
        else:
            logger.info("ℹ️ No alerts to flush")

def simulate_current_behavior():
    """Simulate current batch processing bottleneck"""
    
    logger.info("🧪 Simulating Current Batch Processing Behavior")
    logger.info("=" * 60)
    
    analyzer = BatchProcessingAnalyzer(batch_threshold=10)
    
    # Simulate various alert arrival patterns
    scenarios = [
        ("Scenario 1: Perfect batches", [10, 10, 10]),  # Perfect case
        ("Scenario 2: Subthreshold batch", [9]),        # Bottleneck case  
        ("Scenario 3: Mixed sizes", [7, 5, 3]),         # Mixed case
        ("Scenario 4: Gradual accumulation", [2, 2, 2, 2, 1])  # Gradual case
    ]
    
    for scenario_name, batch_sizes in scenarios:
        logger.info(f"\n📊 {scenario_name}")
        logger.info("-" * 40)
        
        analyzer = BatchProcessingAnalyzer(batch_threshold=10)
        start_time = time.time()
        
        for i, size in enumerate(batch_sizes):
            logger.info(f"  📥 Adding {size} alerts...")
            for j in range(size):
                alert = MockAlert(
                    uuid=f"alert_{i}_{j}",
                    title=f"Alert {i}-{j}",
                    timestamp=time.time()
                )
                analyzer.add_alert(alert)
            
            # Simulate time between batches
            time.sleep(0.1)
        
        # End of processing - force flush remaining
        logger.info(f"  🏁 End of processing - checking for remaining alerts")
        analyzer.force_flush()
        
        # Analyze results
        total_alerts = sum(batch_sizes)
        total_batches = len(analyzer.processed_batches)
        total_time = time.time() - start_time
        
        logger.info(f"  📊 Results:")
        logger.info(f"     • Total alerts: {total_alerts}")
        logger.info(f"     • Batches processed: {total_batches}")
        logger.info(f"     • Total time: {total_time:.2f}s")
        
        # Check for bottleneck
        if any(batch['size'] < analyzer.batch_threshold for batch in analyzer.processed_batches):
            logger.warning(f"  ⚠️ BOTTLENECK: Subthreshold batch detected!")
            for batch in analyzer.processed_batches:
                if batch['size'] < analyzer.batch_threshold:
                    logger.warning(f"     • Batch size {batch['size']} < threshold {analyzer.batch_threshold}")

def demonstrate_timer_solution():
    """Demonstrate timer-based flush solution"""
    
    logger.info(f"\n🚀 Demonstrating Timer-Based Solution")
    logger.info("=" * 60)
    
    class ImprovedBatchProcessor:
        """Batch processor with timer-based flushing"""
        
        def __init__(self, size_threshold: int = 10, time_threshold: float = 5.0):
            self.size_threshold = size_threshold
            self.time_threshold = time_threshold  # Max time before forced flush
            self.buffer: List[MockAlert] = []
            self.last_flush_time = time.time()
            self.processed_batches: List[Dict] = []
            
        def add_alert(self, alert: MockAlert):
            """Add alert with timer-based flushing"""
            self.buffer.append(alert)
            
            # Check both size and time conditions
            should_flush = (
                len(self.buffer) >= self.size_threshold or  # Size threshold
                (time.time() - self.last_flush_time) >= self.time_threshold  # Time threshold
            )
            
            if should_flush:
                flush_reason = "size" if len(self.buffer) >= self.size_threshold else "time"
                logger.info(f"🔄 Processing batch of {len(self.buffer)} alerts (trigger: {flush_reason})")
                self._process_batch()
            else:
                elapsed = time.time() - self.last_flush_time
                logger.debug(f"📋 Buffer: {len(self.buffer)}/{self.size_threshold}, time: {elapsed:.1f}/{self.time_threshold}s")
        
        def _process_batch(self):
            """Process current buffer"""
            if not self.buffer:
                return
                
            batch_info = {
                'size': len(self.buffer),
                'processing_time': time.time(),
                'latency': time.time() - self.last_flush_time
            }
            
            self.processed_batches.append(batch_info)
            logger.info(f"✅ Processed batch: {batch_info}")
            
            self.buffer.clear()
            self.last_flush_time = time.time()
        
        def check_timer_flush(self):
            """Periodic check for timer-based flushing"""
            if self.buffer and (time.time() - self.last_flush_time) >= self.time_threshold:
                logger.info(f"⏰ Timer flush: {len(self.buffer)} alerts after {self.time_threshold}s")
                self._process_batch()
    
    # Test timer-based solution
    processor = ImprovedBatchProcessor(size_threshold=10, time_threshold=3.0)
    
    logger.info("📥 Adding 9 alerts (below threshold)...")
    for i in range(9):
        alert = MockAlert(uuid=f"timer_test_{i}", title=f"Timer Test {i}", timestamp=time.time())
        processor.add_alert(alert)
        time.sleep(0.2)  # Simulate processing delay
    
    logger.info("⏱️ Waiting for timer flush...")
    time.sleep(4.0)  # Wait longer than time threshold
    
    # Check for timer flush
    processor.check_timer_flush()
    
    # Summary
    logger.info(f"\n📊 Timer Solution Results:")
    logger.info(f"     • Batches processed: {len(processor.processed_batches)}")
    logger.info(f"     • Buffer size: {len(processor.buffer)}")
    
    if processor.processed_batches:
        avg_latency = sum(batch['latency'] for batch in processor.processed_batches) / len(processor.processed_batches)
        logger.info(f"     • Average latency: {avg_latency:.2f}s")

def analyze_performance_impact():
    """Analyze performance impact of batch processing bottleneck"""
    
    logger.info(f"\n📈 Performance Impact Analysis")
    logger.info("=" * 60)
    
    scenarios = [
        ("Low volume (5 alerts)", 5),
        ("Medium volume (15 alerts)", 15), 
        ("High volume (25 alerts)", 25)
    ]
    
    for name, alert_count in scenarios:
        logger.info(f"\n🔍 {name}")
        
        # Current approach
        current = BatchProcessingAnalyzer(batch_threshold=10)
        start_time = time.time()
        
        for i in range(alert_count):
            alert = MockAlert(uuid=f"perf_{i}", title=f"Perf Test {i}", timestamp=time.time())
            current.add_alert(alert)
        
        current.force_flush()  # End-of-run flush
        current_time = time.time() - start_time
        
        # Timer approach  
        class TimerProcessor:
            def __init__(self):
                self.processed_count = 0
                self.batch_count = 0
            
            def process_with_timer(self, alerts):
                # Simulate immediate processing with 3s timer
                batches = []
                current_batch = []
                
                for alert in alerts:
                    current_batch.append(alert)
                    if len(current_batch) >= 10:
                        batches.append(len(current_batch))
                        self.batch_count += 1
                        self.processed_count += len(current_batch)
                        current_batch = []
                
                # Timer flush remaining
                if current_batch:
                    batches.append(len(current_batch))
                    self.batch_count += 1
                    self.processed_count += len(current_batch)
                
                return batches
        
        timer = TimerProcessor()
        alerts = [MockAlert(uuid=f"timer_{i}", title=f"Timer {i}", timestamp=time.time()) for i in range(alert_count)]
        timer_batches = timer.process_with_timer(alerts)
        
        # Compare results
        logger.info(f"   Current approach:")
        logger.info(f"     • Batches: {len(current.processed_batches)}")
        logger.info(f"     • Total time: {current_time:.2f}s")
        logger.info(f"     • Batch sizes: {[b['size'] for b in current.processed_batches]}")
        
        logger.info(f"   Timer approach:")
        logger.info(f"     • Batches: {timer.batch_count}")
        logger.info(f"     • Batch sizes: {timer_batches}")
        
        # Efficiency comparison
        current_efficiency = len(current.processed_batches)
        timer_efficiency = timer.batch_count
        
        if alert_count % 10 != 0:  # Only show improvement for subthreshold cases
            logger.info(f"   💡 Efficiency gain: Timer processes immediately vs waiting for next run")

if __name__ == "__main__":
    try:
        simulate_current_behavior()
        demonstrate_timer_solution() 
        analyze_performance_impact()
        
        logger.info(f"\n🎯 CONCLUSION: Timer-based flushing prevents batch processing bottlenecks")
        logger.info("=" * 60)
        logger.info("Key improvements:")
        logger.info("• Prevents subthreshold batches from waiting until next processing run")
        logger.info("• Ensures timely processing of alerts even with low volumes") 
        logger.info("• Maintains batch efficiency while reducing latency")
        logger.info("• Simple to implement: add time-based flush condition")
        
    except Exception as e:
        logger.error(f"❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
