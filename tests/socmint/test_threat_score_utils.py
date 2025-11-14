#!/usr/bin/env python3
"""
Test threat score components utilities and API exposure
"""

import unittest
import sys
sys.path.insert(0, '/home/zika/sentinel_ai_rss')

from threat_score_utils import (
    format_score_components,
    calculate_score_impact,
    get_socmint_details,
    format_for_ui
)


class TestThreatScoreUtils(unittest.TestCase):
    
    def setUp(self):
        """Sample components for testing."""
        self.sample_components = {
            "socmint_raw": 15.0,
            "socmint_weighted": 4.5,
            "socmint_weight": 0.3,
            "base_score": 60.0,
            "final_score": 64.5
        }
    
    def test_format_score_components(self):
        """Test component formatting."""
        result = format_score_components(self.sample_components)
        
        self.assertTrue(result['available'])
        self.assertIn('breakdown', result)
        self.assertIn('socmint', result['breakdown'])
        
        socmint = result['breakdown']['socmint']
        self.assertEqual(socmint['raw_score'], 15.0)
        self.assertEqual(socmint['weighted_contribution'], 4.5)
        self.assertEqual(socmint['weight_percent'], 30)
    
    def test_format_empty_components(self):
        """Test handling of missing components."""
        result = format_score_components(None)
        self.assertFalse(result['available'])
        
        result = format_score_components({})
        self.assertFalse(result['available'])
    
    def test_calculate_score_impact(self):
        """Test impact calculation."""
        result = calculate_score_impact(self.sample_components)
        
        self.assertTrue(result['available'])
        self.assertEqual(result['total_score'], 64.5)
        self.assertEqual(len(result['factors']), 2)  # SOCMINT + Base
        
        # Check SOCMINT factor
        socmint_factor = next(f for f in result['factors'] if f['name'] == 'SOCMINT')
        self.assertEqual(socmint_factor['impact'], 4.5)
        self.assertGreater(socmint_factor['impact_percent'], 0)
    
    def test_get_socmint_details(self):
        """Test SOCMINT detail extraction."""
        result = get_socmint_details(self.sample_components)
        
        self.assertTrue(result['available'])
        self.assertEqual(result['raw_score'], 15.0)
        self.assertEqual(result['weighted_score'], 4.5)
        self.assertGreater(len(result['estimated_factors']), 0)
    
    def test_get_socmint_details_no_data(self):
        """Test SOCMINT details with no SOCMINT data."""
        components = {"base_score": 60.0, "final_score": 60.0}
        result = get_socmint_details(components)
        
        self.assertFalse(result['available'])
        self.assertIn('message', result)
    
    def test_format_for_ui(self):
        """Test UI formatting."""
        result = format_for_ui(self.sample_components)
        
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        
        # Check structure
        for factor in result:
            self.assertIn('label', factor)
            self.assertIn('value', factor)
            self.assertIn('percentage', factor)
            self.assertIn('color', factor)
    
    def test_format_for_ui_empty(self):
        """Test UI formatting with empty components."""
        result = format_for_ui(None)
        self.assertEqual(result, [])
        
        result = format_for_ui({})
        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main()
