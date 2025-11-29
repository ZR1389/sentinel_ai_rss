import unittest
from services.threat_engine import calculate_socmint_score, is_recent
from datetime import datetime, timedelta

class TestCalculateSocmintScore(unittest.TestCase):
    def test_followers_thresholds(self):
        # Low followers
        s1 = calculate_socmint_score({'profile': {'followersCount': 500}, 'posts': []})
        # Medium followers
        s2 = calculate_socmint_score({'profile': {'followersCount': 5000}, 'posts': []})
        # High followers
        s3 = calculate_socmint_score({'profile': {'followersCount': 15000}, 'posts': []})
        # Very high followers
        s4 = calculate_socmint_score({'profile': {'followersCount': 250000}, 'posts': []})
        self.assertTrue(s1 >= 0)
        self.assertGreater(s2, s1)
        self.assertGreater(s3, s2)
        self.assertGreater(s4, s3)

    def test_verified_penalty(self):
        s_unverified = calculate_socmint_score({'profile': {'followersCount': 15000, 'verified': False}, 'posts': []})
        s_verified = calculate_socmint_score({'profile': {'followersCount': 15000, 'verified': True}, 'posts': []})
        self.assertLess(s_verified, s_unverified)

    def test_recent_activity_bonus(self):
        recent_ts = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        stale_ts = (datetime.utcnow() - timedelta(days=40)).strftime('%Y-%m-%dT%H:%M:%SZ')
        s_recent = calculate_socmint_score({
            'profile': {'followersCount': 1000},
            'posts': [{'timestamp': recent_ts, 'text': ''}]
        })
        s_stale = calculate_socmint_score({
            'profile': {'followersCount': 1000},
            'posts': [{'timestamp': stale_ts, 'text': ''}]
        })
        self.assertTrue(is_recent(recent_ts, days=7))
        self.assertFalse(is_recent(stale_ts, days=7))
        self.assertGreaterEqual(s_recent - s_stale, 9.0)

    def test_ioc_detection_bonus(self):
        s_ioc = calculate_socmint_score({
            'profile': {'followersCount': 0},
            'posts': [
                {'timestamp': '2025-11-10T10:00:00Z', 'text': 'CVE-2024-0001'},
                {'timestamp': '2025-11-11T10:00:00Z', 'text': '1.2.3.4 indicator'},
            ]
        })
        s_no_ioc = calculate_socmint_score({
            'profile': {'followersCount': 0},
            'posts': [
                {'timestamp': '2025-11-10T10:00:00Z', 'text': 'hello world'},
            ]
        })
        self.assertGreater(s_ioc, s_no_ioc)

if __name__ == '__main__':
    unittest.main()
