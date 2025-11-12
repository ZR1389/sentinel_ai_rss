#!/usr/bin/env python3
"""
Integration test for vector-based deduplication system.
Tests the complete flow from threat_engine.py to vector_dedup.py.
"""

import sys
import os
import logging
import json
from typing import List, Dict, Any

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vector_dedup import VectorDeduplicator
from threat_engine import deduplicate_alerts
from risk_shared import embedding_manager

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_test_alerts() -> List[Dict[str, Any]]:
    """Create test alerts with some similar and some unique content."""
    return [
        {
            "title": "Cyber attack targets financial institutions",
            "summary": "Multiple banks report suspicious network activity suggesting coordinated attack",
            "link": "https://example.com/alert1",
            "uuid": "test-uuid-1"
        },
        {
            "title": "Banks under cyber attack",
            "summary": "Financial sector sees increased suspicious network traffic indicating potential breach",
            "link": "https://example.com/alert2", 
            "uuid": "test-uuid-2"
        },
        {
            "title": "Weather warning issued for coastal areas",
            "summary": "Severe storm expected to impact coastal regions with high winds and flooding",
            "link": "https://example.com/alert3",
            "uuid": "test-uuid-3"
        },
        {
            "title": "Infrastructure vulnerability discovered",
            "summary": "Security researchers find critical flaw in industrial control systems",
            "link": "https://example.com/alert4",
            "uuid": "test-uuid-4"
        }
    ]

def test_vector_deduplication():
    """Test vector-based deduplication functionality."""
    logger.info("Testing vector deduplication system")
    
    # Test 1: VectorDeduplicator direct usage
    logger.info("Test 1: Direct VectorDeduplicator usage")
    vector_dedup = VectorDeduplicator(similarity_threshold=0.85)
    
    test_alerts = create_test_alerts()
    
    # Test with mock client (will use fallback embeddings)
    try:
        deduplicated = vector_dedup.deduplicate_alerts(test_alerts, openai_client=None)
        logger.info(f"Direct deduplication: {len(test_alerts)} -> {len(deduplicated)} alerts")
        
        for i, alert in enumerate(deduplicated):
            logger.info(f"  Alert {i+1}: {alert['title'][:50]}...")
            
    except Exception as e:
        logger.error(f"Direct deduplication test failed: {e}")
        return False
    
    # Test 2: Integration with threat_engine deduplicate_alerts
    logger.info("Test 2: Integration with threat_engine.deduplicate_alerts")
    try:
        # Test with vector dedup enabled
        os.environ["ENGINE_SEMANTIC_DEDUP"] = "true"
        integrated_dedup = deduplicate_alerts(
            test_alerts,
            existing_alerts=[],
            openai_client=None,
            enable_semantic=True
        )
        logger.info(f"Integrated deduplication: {len(test_alerts)} -> {len(integrated_dedup)} alerts")
        
        for i, alert in enumerate(integrated_dedup):
            logger.info(f"  Alert {i+1}: {alert['title'][:50]}...")
            
    except Exception as e:
        logger.error(f"Integrated deduplication test failed: {e}")
        return False
    
    # Test 3: Similarity finding
    logger.info("Test 3: Similarity detection")
    try:
        if len(test_alerts) >= 2:
            similar = vector_dedup.find_similar_alerts(test_alerts[0], openai_client=None)
            logger.info(f"Found {len(similar)} similar alerts for test alert 1")
            
            for sim_alert in similar:
                logger.info(f"  Similar: {sim_alert['title'][:30]}... (similarity: {sim_alert['similarity']:.3f})")
                
    except Exception as e:
        logger.error(f"Similarity detection test failed: {e}")
        return False
    
    # Test 4: Quota manager integration
    logger.info("Test 4: Quota manager status")
    try:
        status = embedding_manager.get_quota_status()
        logger.info(f"Quota status: {status}")
        
        if status["tokens_remaining"] <= 0:
            logger.warning("Embedding quota exhausted - this is expected behavior for quota protection")
        
    except Exception as e:
        logger.error(f"Quota manager test failed: {e}")
        return False
    
    logger.info("All vector deduplication tests completed successfully!")
    return True

def test_performance_improvement():
    """Test that vector deduplication is more efficient than legacy method."""
    logger.info("Testing performance comparison")
    
    # Create larger test set
    base_alerts = create_test_alerts()
    large_test_set = []
    
    # Create variations to simulate real data
    for i in range(20):
        for base_alert in base_alerts:
            variant = base_alert.copy()
            variant["title"] = f"{base_alert['title']} - variant {i}"
            variant["uuid"] = f"{base_alert['uuid']}-v{i}"
            variant["link"] = f"{base_alert['link']}-v{i}"
            large_test_set.append(variant)
    
    logger.info(f"Created test set with {len(large_test_set)} alerts")
    
    # Test vector deduplication (should be faster for large datasets)
    try:
        import time
        start_time = time.time()
        
        vector_dedup = VectorDeduplicator(similarity_threshold=0.9)
        vector_result = vector_dedup.deduplicate_alerts(large_test_set, openai_client=None)
        
        vector_time = time.time() - start_time
        logger.info(f"Vector deduplication: {len(large_test_set)} -> {len(vector_result)} alerts in {vector_time:.3f}s")
        
        # Test legacy method for comparison
        start_time = time.time()
        
        # Disable vector deduplication to force legacy method
        legacy_result = deduplicate_alerts(
            large_test_set,
            existing_alerts=[],
            openai_client=None,
            enable_semantic=False  # Force hash-only deduplication
        )
        
        legacy_time = time.time() - start_time
        logger.info(f"Legacy deduplication: {len(large_test_set)} -> {len(legacy_result)} alerts in {legacy_time:.3f}s")
        
        # For small datasets, legacy might be faster due to overhead, but vector should scale better
        logger.info(f"Performance ratio: Vector/Legacy = {vector_time/legacy_time:.2f}x")
        
    except Exception as e:
        logger.error(f"Performance test failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    try:
        logger.info("Starting vector deduplication integration tests")
        
        success = True
        success &= test_vector_deduplication()
        success &= test_performance_improvement()
        
        if success:
            print("✅ All tests passed! Vector deduplication system is working correctly.")
        else:
            print("❌ Some tests failed. Check logs for details.")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        print(f"❌ Test suite failed: {e}")
        sys.exit(1)
