import pytest
import os
import json
from risk_processor import get_clean_alerts, generate_fallback_summary

def test_alert_structure():
    alerts = get_clean_alerts(region="Afghanistan", limit=2, summarize=True, user_email="test@example.com", session_id="test1", use_telegram=False)
    assert isinstance(alerts, list)
    for alert in alerts:
        assert "title" in alert
        assert "summary" in alert
        assert "score" in alert
        assert "type" in alert
        assert "threat_label" in alert
        assert "gpt_summary" in alert or "en_snippet" in alert
        assert "keyword_weight" in alert

def test_keyword_weighting_effect():
    alert = {
        "title": "Assassination plot foiled in Kabul",
        "summary": "Police report foiling an assassination attempt targeting a diplomat."
    }
    from risk_processor import compute_keyword_weight
    weight = compute_keyword_weight(alert["title"] + " " + alert["summary"])
    assert weight >= 30  # "assassination" = 30

def test_adaptive_relevance_scoring():
    alert = {"title": "Bombing in Kabul", "summary": "A bombing occurred near the airport."}
    from risk_processor import llm_relevance_score
    score = llm_relevance_score(alert, region="Afghanistan", city="Kabul")
    assert 0.0 <= score <= 1.0

def test_cache_expiry_and_size():
    from risk_processor import summarize_with_security_focus_cached
    summarize_fn = summarize_with_security_focus_cached(lambda x: "dummy summary")
    for i in range(12000):  # Exceed cache max
        summarize_fn(f"test text {i}")
    # Check file size and count
    with open("summary_cache.json", "r") as f:
        data = json.load(f)
        assert len(data) <= 10000

def test_fallback_summary():
    summary = generate_fallback_summary(region="Atlantis", threat_type="Unknown")
    assert isinstance(summary, str) and summary.strip()

def test_telegram_toggle():
    alerts = get_clean_alerts(region="Afghanistan", limit=2, summarize=True, user_email="test@example.com", session_id="test2", use_telegram=True)
    # Just assert runs and returns alerts
    assert isinstance(alerts, list)

if __name__ == "__main__":
    pytest.main([os.path.abspath(__file__)])