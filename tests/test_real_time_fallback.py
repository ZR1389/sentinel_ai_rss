"""Tests for Phase 4 Real-Time Fallback Manager.

These are lightweight, deterministic tests using a stub fetch function and
direct manipulation of CoverageMonitor internal state.

Run:
    python test_real_time_fallback.py
"""

import time
from typing import List, Dict, Any

from monitoring.coverage_monitor import CoverageMonitor, _coverage_monitor  # type: ignore
from real_time_fallback import RealTimeFallbackManager


def _make_monitor_with_locations(locs: List[Dict[str, Any]]) -> CoverageMonitor:
    """Build a CoverageMonitor and inject geographic coverage entries.
    Each dict supports keys: country, region, alert_count_7d, alert_count_30d, last_alert_timestamp
    """
    mon = CoverageMonitor()
    # Replace global instance for manager usage
    import coverage_monitor as cm
    cm._coverage_monitor = mon  # type: ignore
    for entry in locs:
        country = entry["country"]
        region = entry.get("region") or "unknown"
        key = f"{country}:{region}"
        cov = cm.GeographicCoverage(country=country, region=entry.get("region"))
        cov.alert_count_7d = entry.get("alert_count_7d", 0)
        cov.alert_count_30d = entry.get("alert_count_30d", cov.alert_count_7d)
        cov.last_alert_timestamp = entry.get("last_alert_timestamp")
        mon._state.geographic_coverage[key] = cov  # type: ignore
    return mon


def stub_fetch_factory(tag: str):
    def _stub(url: str) -> List[Dict[str, Any]]:
        return [
            {"title": f"Security update in {tag}", "summary": f"Latest events impacting {tag}", "link": url},
            {"title": f"Economic news - {tag}", "summary": "Markets", "link": url},
        ]
    return _stub


def test_no_gaps_returns_empty():
    _make_monitor_with_locations([
        {"country": "France", "alert_count_7d": 7, "last_alert_timestamp": time.time()},
    ])
    mgr = RealTimeFallbackManager(fetch_func=stub_fetch_factory("France"))
    attempts = mgr.trigger_for_gaps()
    assert attempts == [], f"Expected no attempts, got {attempts}"
    print("test_no_gaps_returns_empty: OK")


def test_sparse_gap_country_feed_success():
    _make_monitor_with_locations([
        {"country": "France", "alert_count_7d": 1, "last_alert_timestamp": time.time()},
    ])
    mgr = RealTimeFallbackManager(fetch_func=stub_fetch_factory("France"))
    attempts = mgr.trigger_for_gaps()
    assert len(attempts) == 1, "Expected one attempt for France"
    a = attempts[0]
    assert a.feed_type == "country", f"Expected country feed, got {a.feed_type}"
    assert a.created_alerts > 0, "Expected synthetic alerts created"
    assert a.status == "success", f"Expected success status, got {a.status}"
    # Verify synthetic counters increased
    import coverage_monitor as cm
    key = "France:unknown"
    cov = cm._coverage_monitor._state.geographic_coverage.get(key)  # type: ignore
    assert cov and cov.synthetic_count_7d > 0, "Expected synthetic_count_7d to increase"
    print("test_sparse_gap_country_feed_success: OK")


def test_global_feed_used_when_country_missing():
    _make_monitor_with_locations([
        {"country": "Atlantis", "alert_count_7d": 0, "last_alert_timestamp": time.time()},
    ])
    mgr = RealTimeFallbackManager(fetch_func=stub_fetch_factory("Atlantis"))
    attempts = mgr.trigger_for_gaps()
    assert len(attempts) == 1, "Expected one attempt for Atlantis"
    a = attempts[0]
    assert a.feed_type == "global", f"Expected global feed fallback, got {a.feed_type}"
    assert a.created_alerts > 0, "Expected synthetic alerts"
    import coverage_monitor as cm
    key = "Atlantis:unknown"
    cov = cm._coverage_monitor._state.geographic_coverage.get(key)  # type: ignore
    assert cov and cov.synthetic_count_7d > 0, "Expected synthetic_count_7d to increase"
    print("test_global_feed_used_when_country_missing: OK")


def test_cooldown_and_attempt_limit():
    _make_monitor_with_locations([
        {"country": "Serbia", "alert_count_7d": 0, "last_alert_timestamp": time.time()},
    ])
    mgr = RealTimeFallbackManager(fetch_func=stub_fetch_factory("Serbia"), max_attempts_per_day=1, location_cooldown_hours=24)
    first = mgr.trigger_for_gaps()
    assert len(first) == 1, "First attempt should run"
    second = mgr.trigger_for_gaps()
    assert len(second) == 0, "Second attempt should be blocked by cooldown/limit"
    print("test_cooldown_and_attempt_limit: OK")


def run_all():
    test_no_gaps_returns_empty()
    test_sparse_gap_country_feed_success()
    test_global_feed_used_when_country_missing()
    test_cooldown_and_attempt_limit()
    print("\nALL REAL-TIME FALLBACK TESTS PASSED")


if __name__ == "__main__":
    run_all()
