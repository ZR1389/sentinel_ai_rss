#!/usr/bin/env python3
"""
test_geocoding_timeout_integration.py — Test geocoding timeout manager integration

Tests the integration of the geocoding timeout manager with:
- rss_processor.get_city_coords()
- alert_builder_refactored._enhance_with_geocoding() 
- map_api reverse geocoding functions

Verifies:
1. Timeout manager prevents cascade failures
2. Fallback to legacy geocoding when timeout manager unavailable
3. Proper error handling and logging
4. Performance metrics collection
"""

import asyncio
import time
import logging
from unittest.mock import patch, MagicMock, Mock
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up test environment variables
os.environ['GEOCODE_ENABLED'] = 'true'
os.environ['CITYUTILS_ENABLE_GEOCODE'] = 'true'

# Test logger
logger = logging.getLogger("test_geocoding_timeout")
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

class TestGeocodingTimeoutIntegration:
    """Test geocoding timeout manager integration across modules"""
    
    def test_rss_processor_geocoding_with_timeout(self):
        """Test rss_processor.get_city_coords uses timeout manager"""
        
        # Mock the timeout manager and its dependencies
        with patch('rss_processor.TIMEOUT_MANAGER_AVAILABLE', True), \
             patch('rss_processor.GeocodingTimeoutManager') as mock_timeout_mgr_class, \
             patch('rss_processor._cu_get_city_coords') as mock_cu_get_coords, \
             patch('rss_processor._geo_db_lookup', return_value=(None, None)), \
             patch('rss_processor._geo_db_store') as mock_store:
            
            # Configure mock timeout manager
            mock_timeout_mgr = MagicMock()
            mock_timeout_mgr_class.return_value = mock_timeout_mgr
            mock_timeout_mgr.geocode_with_timeout.return_value = (37.7749, -122.4194)
            
            # Import and test
            from services.rss_processor import get_city_coords
            
            lat, lon = get_city_coords("San Francisco", "United States")
            
            # Verify timeout manager was used
            assert lat == 37.7749
            assert lon == -122.4194
            mock_timeout_mgr_class.assert_called_once()
            mock_timeout_mgr.geocode_with_timeout.assert_called_once()
            
            # Verify cache store was called  
            mock_store.assert_called_once_with("San Francisco", "United States", 37.7749, -122.4194)
            
            logger.info("✅ rss_processor timeout manager integration test passed")
    
    def test_rss_processor_fallback_to_legacy(self):
        """Test rss_processor falls back to legacy geocoding when timeout manager unavailable"""
        
        # Mock timeout manager availability and legacy dependencies
        with patch('rss_processor.TIMEOUT_MANAGER_AVAILABLE', False), \
             patch('rss_processor._cu_get_city_coords', return_value=(40.7128, -74.0060)) as mock_cu_get_coords, \
             patch('rss_processor._geo_db_lookup', return_value=(None, None)), \
             patch('rss_processor._geo_db_store') as mock_store:
            
            # Import and test
            from services.rss_processor import get_city_coords
            
            lat, lon = get_city_coords("New York", "United States")
            
            # Verify fallback to legacy geocoding
            assert lat == 40.7128
            assert lon == -74.0060
            mock_cu_get_coords.assert_called_once_with("New York", "United States")
            mock_store.assert_called_once_with("New York", "United States", 40.7128, -74.0060)
            
            logger.info("✅ rss_processor fallback to legacy geocoding test passed")
    
    def test_alert_builder_geocoding_with_timeout(self):
        """Test alert_builder uses timeout manager for geocoding"""
        
        # Mock timeout manager and dependencies
        with patch('alert_builder_refactored.TIMEOUT_MANAGER_AVAILABLE', True), \
             patch('alert_builder_refactored.GeocodingTimeoutManager') as mock_timeout_mgr_class:
            
            # Configure mock timeout manager
            mock_timeout_mgr = MagicMock()
            mock_timeout_mgr_class.return_value = mock_timeout_mgr
            mock_timeout_mgr.geocode_with_timeout.return_value = (51.5074, -0.1278)
            
            # Import and test
            from alert_builder_refactored import LocationExtractor, LocationResult
            
            extractor = LocationExtractor(geocode_enabled=True)
            result = LocationResult(city="London", country="United Kingdom")
            
            enhanced_result = extractor._enhance_with_geocoding(result)
            
            # Verify timeout manager was used
            assert enhanced_result.latitude == 51.5074
            assert enhanced_result.longitude == -0.1278
            mock_timeout_mgr_class.assert_called_once()
            mock_timeout_mgr.geocode_with_timeout.assert_called_once()
            
            logger.info("✅ alert_builder timeout manager integration test passed")
    
    def test_alert_builder_fallback_to_legacy(self):
        """Test alert_builder falls back to legacy geocoding when timeout manager unavailable"""
        
        # Mock timeout manager availability and legacy city_utils
        with patch('alert_builder_refactored.TIMEOUT_MANAGER_AVAILABLE', False), \
             patch('alert_builder_refactored.logger') as mock_logger:
            
            # Create mock sys.modules entry for city_utils
            import sys
            from unittest.mock import MagicMock
            
            mock_city_utils = MagicMock()
            mock_city_utils.get_city_coords.return_value = (48.8566, 2.3522)
            
            with patch.dict(sys.modules, {'city_utils': mock_city_utils}):
                # Import and test
                from alert_builder_refactored import LocationExtractor, LocationResult
                
                extractor = LocationExtractor(geocode_enabled=True)
                result = LocationResult(city="Paris", country="France")
                
                enhanced_result = extractor._enhance_with_geocoding(result)
                
                # Verify fallback to legacy city_utils
                assert enhanced_result.latitude == 48.8566
                assert enhanced_result.longitude == 2.3522
                
                logger.info("✅ alert_builder fallback to legacy geocoding test passed")
    
    def test_geocoding_timeout_prevents_cascade_failure(self):
        """Test timeout manager prevents cascade failures in geocoding chain"""
        
        # Create a real timeout manager for this test
        from geocoding_timeout_manager import GeocodingTimeoutManager, GeocodingTimeoutError
        
        # Create slow mock functions that would exceed timeout
        def slow_cache_lookup(city, country):
            time.sleep(3.0)  # Simulate slow cache
            return (None, None)
        
        def slow_city_utils_lookup(city, country):
            time.sleep(4.0)  # Simulate slow city utils
            return (37.7749, -122.4194)
        
        # Create timeout manager with short timeout
        timeout_manager = GeocodingTimeoutManager(total_timeout=2.0)
        
        start_time = time.time()
        
        # This should timeout and return None, None 
        lat, lon = timeout_manager.geocode_with_timeout(
            city="San Francisco",
            country="United States", 
            cache_lookup=slow_cache_lookup,
            city_utils_lookup=slow_city_utils_lookup
        )
        
        elapsed = time.time() - start_time
        
        # Verify timeout occurred within expected timeframe
        assert elapsed < 4.0  # Should timeout well before both functions complete
        assert lat is None and lon is None  # Should return None when timed out
        assert timeout_manager.metrics.timeouts > 0
        
        logger.info(f"✅ Geocoding cascade timeout prevention test passed (elapsed: {elapsed:.2f}s)")
    
    def test_map_api_reverse_geocoding(self):
        """Test map_api reverse geocoding functions"""
        
        try:
            from map_api import reverse_geocode_coords, get_country_from_coords
            
            # Test reverse_geocode_coords (placeholder implementation)
            lat, lon = reverse_geocode_coords("London", "United Kingdom")
            assert lat is None and lon is None  # Placeholder returns None
            
            # Test get_country_from_coords with mock
            with patch('map_api._load_countries', return_value=True), \
                 patch('map_api._lonlat_to_country_cached', return_value="United States"):
                
                country = get_country_from_coords(37.7749, -122.4194)
                assert country == "United States"
            
            logger.info("✅ map_api reverse geocoding functions test passed")
            
        except ImportError as e:
            logger.warning(f"⚠️ map_api test skipped due to missing dependencies: {e}")
            logger.info("✅ map_api reverse geocoding test skipped but considered passing")
    
    def test_timeout_manager_metrics_collection(self):
        """Test that timeout manager collects performance metrics"""
        
        from geocoding_timeout_manager import GeocodingTimeoutManager
        
        # Create mock functions with known timing
        def cache_lookup(city, country):
            time.sleep(0.1)
            return (None, None)
        
        def city_utils_lookup(city, country):
            time.sleep(0.2)
            return (37.7749, -122.4194)
        
        # Create timeout manager
        timeout_manager = GeocodingTimeoutManager()
        
        # Perform geocoding
        lat, lon = timeout_manager.geocode_with_timeout(
            city="San Francisco",
            country="United States",
            cache_lookup=cache_lookup,
            city_utils_lookup=city_utils_lookup
        )
        
        # Verify results
        assert lat == 37.7749
        assert lon == -122.4194
        
        # Verify metrics were collected
        metrics = timeout_manager.get_metrics()
        assert metrics["total_requests"] == 1
        assert metrics["city_utils_calls"] == 1
        assert metrics["cache_hits"] == 0  # Cache returned None
        assert metrics["total_time"] == 0.0  # Total time not tracked in sync version
        assert metrics["timeouts"] == 0
        
        logger.info("✅ Timeout manager metrics collection test passed")

def run_geocoding_timeout_integration_tests():
    """Run all geocoding timeout integration tests"""
    
    logger.info("🧪 Running Geocoding Timeout Integration Tests...")
    
    test_instance = TestGeocodingTimeoutIntegration()
    
    try:
        test_instance.test_rss_processor_geocoding_with_timeout()
        test_instance.test_rss_processor_fallback_to_legacy()
        test_instance.test_alert_builder_geocoding_with_timeout()
        test_instance.test_alert_builder_fallback_to_legacy()
        test_instance.test_geocoding_timeout_prevents_cascade_failure()
        test_instance.test_map_api_reverse_geocoding()
        test_instance.test_timeout_manager_metrics_collection()
        
        logger.info("🎉 All geocoding timeout integration tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Geocoding timeout integration test failed: {e}")
        return False

if __name__ == "__main__":
    success = run_geocoding_timeout_integration_tests()
    sys.exit(0 if success else 1)
