import unittest
from enrichment_stages import ThreatScoringStage, EnrichmentContext

class TestThreatScoringStageSocmint(unittest.TestCase):
    def test_socmint_augmentation_and_components(self):
        alert = {
            'uuid': 'test-socmint-1',
            'title': 'Actor update',
            'summary': 'Actor @malware_king posts new leak on instagram',
            'tags': ['ransomware'],
            'category': 'cyber',
            'threat_score': 60,
            'enrichments': {
                'osint': [
                    {
                        'platform': 'instagram',
                        'identifier': 'malware_king',
                        'url': 'https://instagram.com/malware_king',
                        'data': {
                            'profile': {'followersCount': 15000, 'verified': False},
                            'posts': [{'timestamp': '2025-11-10T10:00:00Z', 'text': 'Indicators: CVE-2024-0001'}]
                        }
                    }
                ]
            }
        }
        context = EnrichmentContext(
            alert_uuid=alert['uuid'],
            full_text=f"{alert['title']}\n{alert['summary']}",
            title=alert['title'],
            summary=alert['summary'],
            location=None,
            triggers=alert['tags'],
        )
        stage = ThreatScoringStage()
        out = stage.process(alert, context)
        # Expect +7.5 (30% of raw ~25: followers 10 + recent 10 + IOC 5)
        self.assertAlmostEqual(out.get('threat_score'), 67.5, places=1)
        comps = out.get('threat_score_components')
        self.assertIsInstance(comps, dict)
        self.assertIn('socmint_raw', comps)
        self.assertIn('socmint_weighted', comps)
        self.assertIn('socmint_weight', comps)

if __name__ == '__main__':
    unittest.main()
