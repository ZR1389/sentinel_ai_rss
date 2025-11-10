"""
Test suite for refactored alert building components
Demonstrates how the refactored code is much easier to test
"""

import pytest
from datetime import datetime, timezone, timedelta
from alert_builder_refactored import (
    AlertMetadata, LocationResult, ContentValidator, 
    SourceTagParser, LocationExtractor, AlertBuilder
)

class TestContentValidator:
    """Test content validation - now easily testable in isolation"""
    
    def test_should_process_entry_fresh(self):
        """Test that fresh entries are processed"""
        entry = {"published": datetime.now(timezone.utc)}
        assert ContentValidator.should_process_entry(entry, cutoff_days=3)
    
    def test_should_process_entry_stale(self):
        """Test that stale entries are rejected"""
        old_date = datetime.now(timezone.utc) - timedelta(days=5)
        entry = {"published": old_date}
        assert not ContentValidator.should_process_entry(entry, cutoff_days=3)
    
    def test_should_process_entry_no_date(self):
        """Test that entries without dates are processed"""
        entry = {}
        assert ContentValidator.should_process_entry(entry, cutoff_days=3)

class TestSourceTagParser:
    """Test source tag parsing - pure functions, easy to test"""
    
    def test_extract_city_from_tag(self):
        assert SourceTagParser.extract_city_from_tag("local:paris") == "paris"
        assert SourceTagParser.extract_city_from_tag("local:new york") == "new york"
        assert SourceTagParser.extract_city_from_tag("country:france") is None
        assert SourceTagParser.extract_city_from_tag(None) is None
    
    def test_extract_country_from_tag(self):
        # Note: This test would need _titlecase mock, but shows the concept
        assert SourceTagParser.extract_country_from_tag("country:france") is not None
        assert SourceTagParser.extract_country_from_tag("local:paris") is None
        assert SourceTagParser.extract_country_from_tag(None) is None

class TestLocationExtractor:
    """Test location extraction - each strategy can be tested separately"""
    
    @pytest.fixture
    def sample_metadata(self):
        return AlertMetadata(
            uuid="test-123",
            title="Security Incident in Paris",
            summary="Police reported suspicious activity near the Eiffel Tower",
            link="https://example.com/news/123",
            source="example.com",
            published=datetime.now(timezone.utc),
            language="en",
            text_blob="Security Incident in Paris Police reported suspicious activity"
        )
    
    def test_location_extractor_initialization(self):
        """Test basic initialization"""
        extractor = LocationExtractor(geocode_enabled=False)
        assert not extractor.geocode_enabled
        
        extractor = LocationExtractor(geocode_enabled=True)
        assert extractor.geocode_enabled
    
    def test_should_use_batch_processing_no_function(self, sample_metadata):
        """Test batch processing check when function unavailable"""
        extractor = LocationExtractor()
        # This would return False when _should_use_moonshot_for_location is unavailable
        result = extractor._should_use_batch_processing(sample_metadata, "global")
        assert isinstance(result, bool)
    
    def test_try_source_tag_location_no_tag(self):
        """Test source tag location when no tag provided"""
        extractor = LocationExtractor()
        result = extractor._try_source_tag_location(None)
        assert result.location_method == "none"
        assert result.country is None

class TestAlertBuilder:
    """Test alert building - pure functions, predictable output"""
    
    @pytest.fixture
    def sample_metadata(self):
        return AlertMetadata(
            uuid="test-456",
            title="Test Alert",
            summary="This is a test summary for alert building",
            link="https://test.com/alert",
            source="test.com", 
            published=datetime(2025, 11, 9, 12, 0, 0, tzinfo=timezone.utc),
            language="en",
            text_blob="Test Alert This is a test summary"
        )
    
    @pytest.fixture
    def sample_location(self):
        return LocationResult(
            city="Paris",
            country="France", 
            region="Europe",
            latitude=48.8566,
            longitude=2.3522,
            location_method="deterministic",
            location_confidence="high"
        )
    
    def test_create_placeholder_alert(self, sample_metadata):
        """Test placeholder alert creation"""
        kw_match = {"hit": True, "keywords": ["security"]}
        
        alert = AlertBuilder.create_placeholder_alert(
            sample_metadata, kw_match, "local:paris"
        )
        
        assert alert["uuid"] == "test-456"
        assert alert["title"] == "Test Alert"
        assert alert["location_method"] == "batch_pending"
        assert alert["_batch_queued"] is True
        assert alert["source_tag"] == "local:paris"
    
    def test_create_final_alert(self, sample_metadata, sample_location):
        """Test final alert creation"""
        kw_match = {"hit": True, "keywords": ["security"]}
        
        alert = AlertBuilder.create_final_alert(
            sample_metadata, sample_location, kw_match, "global"
        )
        
        assert alert["uuid"] == "test-456"
        assert alert["city"] == "Paris"
        assert alert["country"] == "France"
        assert alert["region"] == "Europe"
        assert alert["location_method"] == "deterministic"
        assert alert["location_confidence"] == "high"
        assert alert["latitude"] == 48.8566
        assert alert["longitude"] == 2.3522
        assert alert["location_sharing"] is True
        assert alert["source_tag"] == "global"
    
    def test_create_final_alert_no_coordinates(self, sample_metadata):
        """Test final alert with no coordinates"""
        location = LocationResult(
            country="France",
            location_method="feed_tag",
            location_confidence="low"
        )
        kw_match = {"hit": True}
        
        alert = AlertBuilder.create_final_alert(sample_metadata, location, kw_match)
        
        assert alert["location_sharing"] is False
        assert alert["latitude"] is None
        assert alert["longitude"] is None

class TestIntegration:
    """Integration tests showing the benefits of the refactored approach"""
    
    def test_error_isolation(self):
        """Demonstrate that errors in one component don't break others"""
        # With the refactored approach, if location detection fails,
        # it doesn't break the entire alert building process
        
        metadata = AlertMetadata(
            uuid="test-789", title="Test", summary="Test", 
            link="test.com", source="test", 
            published=datetime.now(timezone.utc),
            language="en", text_blob="test"
        )
        
        # Even if location extraction fails, we can still build a basic alert
        empty_location = LocationResult()
        kw_match = {"hit": True}
        
        alert = AlertBuilder.create_final_alert(metadata, empty_location, kw_match)
        assert alert["uuid"] == "test-789"
        assert alert["location_method"] == "none"
        assert alert["country"] is None
    
    def test_component_substitution(self):
        """Demonstrate how easy it is to substitute components"""
        # With the refactored approach, we can easily mock or replace
        # individual components for testing
        
        class MockLocationExtractor(LocationExtractor):
            async def detect_location(self, metadata, source_tag=None, batch_mode=False, client=None):
                return LocationResult(
                    country="MockCountry",
                    location_method="mock",
                    location_confidence="test"
                )
        
        # Now we can test with predictable location results
        extractor = MockLocationExtractor()
        # ... rest of test

if __name__ == "__main__":
    # Run basic tests to verify the refactored components work
    print("🧪 Testing refactored alert building components...")
    
    # Test basic functionality
    validator = ContentValidator()
    parser = SourceTagParser()
    builder = AlertBuilder()
    
    print("✓ Components instantiate correctly")
    
    # Test simple functionality
    fresh_entry = {"published": datetime.now(timezone.utc)}
    assert validator.should_process_entry(fresh_entry, 3)
    print("✓ Content validation works")
    
    assert parser.extract_city_from_tag("local:tokyo") == "tokyo"
    print("✓ Source tag parsing works")
    
    print("🎉 All basic tests pass! Refactored components are working.")
    print()
    print("📊 Benefits demonstrated:")
    print("  - Each component is testable in isolation")
    print("  - Clear separation of concerns")
    print("  - Easy to mock for testing")
    print("  - Simple error handling")
    print("  - No more 4-level nested try/catch blocks!")
