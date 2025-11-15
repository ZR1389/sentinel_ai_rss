#!/usr/bin/env python3
"""
Test Coverage Monitor - Validates geographic coverage tracking and monitoring
"""

import sys
import logging
from typing import Dict, Any

sys.path.insert(0, '/home/zika/sentinel_ai_rss')

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def test_basic_recording():
    """Test basic alert and extraction recording"""
    from coverage_monitor import CoverageMonitor
    
    logger.info("\n" + "="*60)
    logger.info("TEST 1: Basic Recording")
    logger.info("="*60)
    
    monitor = CoverageMonitor()
    
    # Record some alerts
    monitor.record_alert("Serbia", region="Central Serbia", confidence=0.75, source_count=3)
    monitor.record_alert("Serbia", region="Central Serbia", confidence=0.80, source_count=2)
    monitor.record_alert("Hungary", region="Central Europe", confidence=0.65, source_count=1)
    monitor.record_alert("Egypt", region="Middle East", confidence=0.85, source_count=4)
    
    # Record location extractions
    monitor.record_location_extraction(success=True, method="spacy")
    monitor.record_location_extraction(success=True, method="regex")
    monitor.record_location_extraction(success=False, method=None)
    
    # Record advisory attempts
    monitor.record_advisory_attempt(generated=True)
    monitor.record_advisory_attempt(generated=False, gate_reason="location mismatch")
    monitor.record_advisory_attempt(generated=False, gate_reason="low confidence")
    
    logger.info("✅ Recorded 4 alerts, 3 extractions, 3 advisory attempts")
    
    return True


def test_coverage_gaps():
    """Test coverage gap detection"""
    from coverage_monitor import CoverageMonitor
    import time
    
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Coverage Gap Detection")
    logger.info("="*60)
    
    monitor = CoverageMonitor()
    
    # Well-covered location (many recent alerts)
    for i in range(10):
        monitor.record_alert("France", region="Western Europe", confidence=0.75)
    
    # Sparse coverage (few alerts)
    monitor.record_alert("Iceland", region="Northern Europe", confidence=0.60)
    monitor.record_alert("Iceland", region="Northern Europe", confidence=0.65)
    
    # Get coverage report
    gaps = monitor.get_coverage_gaps(min_alerts_7d=5, max_age_hours=24)
    covered = monitor.get_covered_locations()
    
    logger.info(f"Coverage Gaps Found: {len(gaps)}")
    for gap in gaps:
        logger.info(f"  - {gap['country']} ({gap['region']}): {gap['issues']} - {gap['alert_count_7d']} alerts")
    
    logger.info(f"\nWell-Covered Locations: {len(covered)}")
    for loc in covered:
        logger.info(f"  - {loc['country']} ({loc['region']}): {loc['alert_count_7d']} alerts, {loc['confidence_avg']} avg confidence")
    
    if len(gaps) > 0 and len(covered) > 0:
        logger.info("✅ Gap detection working correctly")
        return True
    else:
        logger.error("❌ Gap detection not working as expected")
        return False


def test_statistics():
    """Test statistics reporting"""
    from coverage_monitor import CoverageMonitor
    
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Statistics Reporting")
    logger.info("="*60)
    
    monitor = CoverageMonitor()
    
    # Record varied data
    for i in range(20):
        monitor.record_alert("UK", region="Western Europe", confidence=0.70 + i*0.01)
    
    for i in range(10):
        monitor.record_location_extraction(success=True, method="spacy")
    for i in range(3):
        monitor.record_location_extraction(success=True, method="regex")
    for i in range(2):
        monitor.record_location_extraction(success=False)
    
    for i in range(15):
        monitor.record_advisory_attempt(generated=True)
    monitor.record_advisory_attempt(generated=False, gate_reason="location mismatch")
    monitor.record_advisory_attempt(generated=False, gate_reason="low confidence")
    monitor.record_advisory_attempt(generated=False, gate_reason="insufficient data")
    
    # Get statistics
    loc_stats = monitor.get_location_extraction_stats()
    gate_stats = monitor.get_advisory_gating_stats()
    
    logger.info("Location Extraction Stats:")
    logger.info(f"  Total Queries: {loc_stats['total_queries']}")
    logger.info(f"  Success Rate: {loc_stats['success_rate']}%")
    logger.info(f"  Methods: spaCy={loc_stats['method_breakdown']['spacy']}, regex={loc_stats['method_breakdown']['regex']}")
    
    logger.info("\nAdvisory Gating Stats:")
    logger.info(f"  Total Attempts: {gate_stats['total_attempts']}")
    logger.info(f"  Success Rate: {gate_stats['success_rate']}%")
    logger.info(f"  Gating Rate: {gate_stats['gating_rate']}%")
    logger.info(f"  Gate Reasons: location={gate_stats['gated_location_mismatch']}, confidence={gate_stats['gated_low_confidence']}, data={gate_stats['gated_insufficient_data']}")
    
    # Validate calculations
    expected_success_rate = (13 / 15) * 100  # 13 successes out of 15 total
    expected_gating_rate = (3 / 18) * 100  # 3 gated out of 18 attempts
    
    if abs(loc_stats['success_rate'] - 86.67) < 1:  # Allow small floating point diff
        logger.info("✅ Location extraction stats correct")
    else:
        logger.error(f"❌ Location extraction stats incorrect: expected ~86.67%, got {loc_stats['success_rate']}%")
    
    if abs(gate_stats['gating_rate'] - expected_gating_rate) < 1:
        logger.info("✅ Advisory gating stats correct")
        return True
    else:
        logger.error(f"❌ Advisory gating stats incorrect: expected ~{expected_gating_rate:.2f}%, got {gate_stats['gating_rate']}%")
        return False


def test_comprehensive_report():
    """Test comprehensive reporting"""
    from coverage_monitor import CoverageMonitor
    
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Comprehensive Report")
    logger.info("="*60)
    
    monitor = CoverageMonitor()
    
    # Populate with realistic but smaller dataset
    countries = [
        ("US", "North America", 8, 0.80),
        ("UK", "Western Europe", 6, 0.75),
        ("Australia", "Oceania", 2, 0.65),  # Sparse
    ]
    
    for country, region, count, confidence in countries:
        for i in range(count):
            monitor.record_alert(country, region=region, confidence=confidence)
    
    # Get comprehensive report
    report = monitor.get_comprehensive_report()
    
    logger.info(f"Timestamp: {report['timestamp']}")
    logger.info(f"Last Updated: {report['last_updated']}")
    
    logger.info("\nGeographic Coverage:")
    logger.info(f"  Total Locations: {report['geographic_coverage']['total_locations']}")
    logger.info(f"  Well-Covered: {report['geographic_coverage']['covered_locations']}")
    logger.info(f"  Gaps: {report['geographic_coverage']['coverage_gaps']}")
    
    if len(report['geographic_coverage']['gaps_detail']) > 0:
        logger.info("  Top Gaps:")
        for gap in report['geographic_coverage']['gaps_detail'][:3]:
            logger.info(f"    - {gap['country']}: {gap['alert_count_7d']} alerts/7d")
    
    # Test JSON export
    json_export = monitor.export_to_json()
    if "geographic_coverage" in json_export and "location_extraction" in json_export:
        logger.info("\n✅ Comprehensive report generated successfully")
        logger.info(f"✅ JSON export working (length: {len(json_export)} chars)")
        return True
    else:
        logger.error("❌ Comprehensive report incomplete")
        return False


def test_log_summary():
    """Test log summary output"""
    from coverage_monitor import CoverageMonitor
    
    logger.info("\n" + "="*60)
    logger.info("TEST 5: Log Summary")
    logger.info("="*60)
    
    monitor = CoverageMonitor()
    
    # Add diverse data
    monitor.record_alert("Serbia", region="Balkans", confidence=0.75, source_count=3)
    monitor.record_alert("Serbia", region="Balkans", confidence=0.80, source_count=2)
    monitor.record_alert("Iceland", region="Nordic", confidence=0.60, source_count=1)
    
    monitor.record_location_extraction(success=True, method="spacy")
    monitor.record_location_extraction(success=True, method="regex")
    monitor.record_location_extraction(success=False)
    
    monitor.record_advisory_attempt(generated=True)
    monitor.record_advisory_attempt(generated=False, gate_reason="location mismatch")
    
    logger.info("\nGenerating log summary:")
    logger.info("-" * 60)
    monitor.log_summary()
    logger.info("-" * 60)
    
    logger.info("✅ Log summary generated")
    return True


def main():
    logger.info("\n" + "#"*60)
    logger.info("# COVERAGE MONITOR TEST SUITE")
    logger.info("#"*60)
    
    results = []
    
    # Run all tests
    results.append(("Basic Recording", test_basic_recording()))
    results.append(("Coverage Gaps", test_coverage_gaps()))
    results.append(("Statistics", test_statistics()))
    results.append(("Comprehensive Report", test_comprehensive_report()))
    results.append(("Log Summary", test_log_summary()))
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    logger.info("="*60)
    logger.info(f"Result: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        logger.info("\n🎉 ALL COVERAGE MONITOR TESTS PASSED!")
        logger.info("\nCoverage Monitor Features:")
        logger.info("  ✓ Geographic coverage tracking")
        logger.info("  ✓ Coverage gap detection")
        logger.info("  ✓ Location extraction metrics")
        logger.info("  ✓ Advisory gating statistics")
        logger.info("  ✓ Comprehensive reporting")
        logger.info("  ✓ JSON export support")
    else:
        logger.error("\n⚠️  SOME TESTS FAILED - Review results above")
    
    logger.info("="*60 + "\n")
    
    return 0 if passed_count == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
