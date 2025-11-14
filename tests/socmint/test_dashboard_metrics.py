import unittest
from socmint_service import SocmintService

class TestSocmintDashboardMetrics(unittest.TestCase):
    def setUp(self):
        self.service = SocmintService()

    def test_dashboard_structure(self):
        data = self.service.get_dashboard_metrics()
        # Top-level keys
        for key in ["timestamp", "platforms", "totals", "daily_usage", "recent_errors", "insights"]:
            self.assertIn(key, data)
        # Platform keys
        self.assertIn("instagram", data["platforms"])  # ensure both platforms present
        self.assertIn("facebook", data["platforms"])  # ensure both platforms present
        ig = data["platforms"]["instagram"]
        fb = data["platforms"]["facebook"]
        # Required metric fields per platform
        metric_fields = ["cache_hits", "cache_misses", "apify_calls", "errors", "hit_rate", "error_rate", "estimated_savings_usd"]
        for f in metric_fields:
            self.assertIn(f, ig)
            self.assertIn(f, fb)
        # Daily usage structure
        du = data["daily_usage"]
        self.assertIn("instagram", du)
        self.assertIn("facebook", du)
        self.assertIn("last_reset", du)
        for plat in ["instagram", "facebook"]:
            self.assertIn("used", du[plat])
            self.assertIn("limit", du[plat])
            self.assertIn("remaining", du[plat])
        # Insights structure
        insights = data["insights"]
        self.assertIsInstance(insights, dict)
        self.assertIn("cache_ttl_optimal", insights)
        self.assertIn("apify_limit_risk", insights)
        self.assertIn("recommendations", insights)
        self.assertIsInstance(insights["recommendations"], list)

if __name__ == '__main__':
    unittest.main()
