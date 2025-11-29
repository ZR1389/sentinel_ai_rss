#!/usr/bin/env python3
"""Test script for /api/stats/overview endpoint"""

import requests
import json
import os
from datetime import datetime

# Get token from environment or prompt
TOKEN = os.getenv("SENTINEL_TOKEN")
if not TOKEN:
    print("Set SENTINEL_TOKEN environment variable or enter token:")
    TOKEN = input("Token: ").strip()

BASE_URL = "https://sentinelairss-production.up.railway.app"
# BASE_URL = "http://localhost:8080"  # Uncomment for local testing

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

def test_stats_overview(days=None):
    """Test the stats overview endpoint"""
    url = f"{BASE_URL}/api/stats/overview"
    if days:
        url += f"?days={days}"
    
    print(f"\n{'='*60}")
    print(f"Testing: GET {url}")
    print(f"{'='*60}")
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ Success!")
            print(f"\nKey Metrics:")
            print(f"  Threats (7d):        {data.get('threats_7d', 0):,}")
            print(f"  Threats (30d):       {data.get('threats_30d', 0):,}")
            print(f"  Trend (7d):          {data.get('trend_7d', 0):+d}%")
            print(f"  Active Monitors:     {data.get('active_monitors', 0)}")
            print(f"  Tracked Locations:   {data.get('tracked_locations', 0)}")
            print(f"  Chat Messages/Month: {data.get('chat_messages_month', 0)}")
            print(f"  Window Days:         {data.get('window_days', 0)}")
            print(f"  Max Window Days:     {data.get('max_window_days', 0)} (plan limit)")
            
            # Severity breakdown
            severity = data.get('severity_breakdown', {})
            print(f"\nSeverity Breakdown (Total: {severity.get('total', 0)}):")
            print(f"  Critical: {severity.get('critical', 0):3d} ({severity.get('critical_pct', 0):5.1f}%)")
            print(f"  High:     {severity.get('high', 0):3d} ({severity.get('high_pct', 0):5.1f}%)")
            print(f"  Medium:   {severity.get('medium', 0):3d} ({severity.get('medium_pct', 0):5.1f}%)")
            print(f"  Low:      {severity.get('low', 0):3d} ({severity.get('low_pct', 0):5.1f}%)")
            
            # Weekly trends
            trends = data.get('weekly_trends', [])
            if trends:
                print(f"\nWeekly Trends ({len(trends)} days):")
                for trend in trends[:5]:  # Show first 5
                    print(f"  {trend['date']}: {trend['count']:3d} threats")
                if len(trends) > 5:
                    print(f"  ... and {len(trends) - 5} more days")
            
            # Top regions
            regions = data.get('top_regions', [])
            if regions:
                print(f"\nTop Regions:")
                for region in regions:
                    print(f"  {region['region']:20s} {region['count']:4d} ({region['percentage']:5.1f}%)")
            
            print(f"\nUpdated: {data.get('updated_at', 'N/A')}")
            
            # Full JSON for debugging
            print(f"\n{'─'*60}")
            print("Full Response JSON:")
            print(json.dumps(data, indent=2))
            
            return True
        else:
            print(f"\n❌ Error {response.status_code}")
            print(response.text)
            return False
            
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("SENTINEL AI - STATS OVERVIEW ENDPOINT TEST")
    print("=" * 60)
    
    # Test default window (plan-based)
    test_stats_overview()
    
    # Test with explicit 7-day window
    input("\nPress Enter to test 7-day window...")
    test_stats_overview(days=7)
    
    # Test with 30-day window
    input("\nPress Enter to test 30-day window (requires PRO plan)...")
    test_stats_overview(days=30)
    
    # Test with 90-day window
    input("\nPress Enter to test 90-day window (requires ENTERPRISE plan)...")
    test_stats_overview(days=90)
    
    print("\n" + "=" * 60)
    print("Testing complete!")
    print("=" * 60)
