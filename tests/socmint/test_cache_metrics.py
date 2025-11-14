import unittest
from socmint_service import (
    SocmintService, 
    get_cache_metrics, 
    reset_cache_metrics,
    log_cache_performance_summary
)

class TestCacheMetrics(unittest.TestCase):
    def setUp(self):
        """Reset metrics before each test."""
        reset_cache_metrics()
    
    def test_metrics_initialization(self):
        """Test metrics start at zero."""
        metrics = get_cache_metrics()
        self.assertEqual(metrics['hits'], 0)
        self.assertEqual(metrics['misses'], 0)
        self.assertEqual(metrics['total_requests'], 0)
        self.assertEqual(metrics['apify_calls'], 0)
        self.assertEqual(metrics['cache_saves'], 0)
        self.assertEqual(metrics['errors'], 0)
        self.assertEqual(metrics['hit_rate_percent'], 0.0)
    
    def test_cache_miss_tracking(self):
        """Test cache miss increments counters."""
        service = SocmintService()
        
        # Trigger cache miss (non-existent entry)
        result = service.get_cached_socmint_data('instagram', 'nonexistent_user', ttl_minutes=120)
        
        self.assertFalse(result['success'])
        
        metrics = get_cache_metrics()
        self.assertEqual(metrics['misses'], 1)
        self.assertEqual(metrics['total_requests'], 1)
        self.assertEqual(metrics['hit_rate_percent'], 0.0)
    
    def test_metrics_reset(self):
        """Test metrics can be reset."""
        service = SocmintService()
        
        # Generate some activity
        service.get_cached_socmint_data('instagram', 'test1', ttl_minutes=120)
        service.get_cached_socmint_data('facebook', 'test2', ttl_minutes=120)
        
        metrics_before = get_cache_metrics()
        self.assertGreater(metrics_before['total_requests'], 0)
        
        # Reset
        reset_cache_metrics()
        
        metrics_after = get_cache_metrics()
        self.assertEqual(metrics_after['total_requests'], 0)
        self.assertEqual(metrics_after['misses'], 0)
    
    def test_hit_rate_calculation(self):
        """Test hit rate percentage is calculated correctly."""
        # Manually increment counters for testing
        from socmint_service import _cache_metrics
        _cache_metrics['total_requests'] = 10
        _cache_metrics['hits'] = 7
        _cache_metrics['misses'] = 3
        
        metrics = get_cache_metrics()
        self.assertEqual(metrics['hit_rate_percent'], 70.0)
    
    def test_log_performance_summary(self):
        """Test performance summary logs without error."""
        service = SocmintService()
        
        # Generate some activity
        service.get_cached_socmint_data('instagram', 'test_user', ttl_minutes=120)
        
        # Should not raise exception
        try:
            log_cache_performance_summary()
            success = True
        except Exception as e:
            print(f"Summary logging failed: {e}")
            success = False
        
        self.assertTrue(success)

if __name__ == '__main__':
    unittest.main()
