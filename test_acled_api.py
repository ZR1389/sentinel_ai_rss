#!/usr/bin/env python3
"""
ACLED API Test Script
Tests different ACLED API endpoints and authentication methods to find the correct one.
"""

import os
import requests
from datetime import datetime, timedelta

# Load from environment
ACLED_EMAIL = os.getenv("ACLED_EMAIL", "info@zikarisk.com")
ACLED_PASSWORD = os.getenv("ACLED_PASSWORD", "")
ACLED_API_KEY = os.getenv("ACLED_API_KEY", "")

print("=" * 80)
print("ACLED API TEST - Finding Correct Endpoint & Auth Method")
print("=" * 80)
print(f"Email: {ACLED_EMAIL}")
print(f"Password: {'*' * len(ACLED_PASSWORD) if ACLED_PASSWORD else 'NOT SET'}")
print(f"API Key: {ACLED_API_KEY[:20] + '...' if len(ACLED_API_KEY) > 20 else ACLED_API_KEY or 'NOT SET'}")
print()

# Test date (yesterday)
test_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
test_country = "Nigeria"

# Test 1: OAuth Token Authentication (Old API)
print("=" * 80)
print("TEST 1: OAuth Authentication (Old Method)")
print("=" * 80)
print("URL: https://acleddata.com/oauth/token")

try:
    response = requests.post(
        "https://acleddata.com/oauth/token",
        data={
            "username": ACLED_EMAIL,
            "password": ACLED_PASSWORD,
            "grant_type": "password",
            "client_id": "acled"
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    print(f"✅ OAuth SUCCESS - Token: {token[:30]}...")
    
    # Test 2: Old API endpoint with Bearer token
    print("\n" + "=" * 80)
    print("TEST 2: Old API Endpoint (acleddata.com/api/acled/read)")
    print("=" * 80)
    
    test_url = "https://acleddata.com/api/acled/read"
    print(f"URL: {test_url}")
    print(f"Params: country={test_country}, event_date={test_date}")
    
    response = requests.get(
        test_url,
        params={
            "country": test_country,
            "event_date": test_date,
            "limit": 5
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        events = data.get("data", []) if isinstance(data, dict) else data
        print(f"✅ OLD API WORKS - Events: {len(events)}")
        if events:
            print(f"Sample event: {events[0].get('event_type', 'N/A')}")
    else:
        print(f"❌ OLD API FAILED: {response.status_code} - {response.text[:200]}")
        
except Exception as e:
    print(f"❌ OAuth or Old API Failed: {e}")

# Test 3: New API with API Key (if available)
print("\n" + "=" * 80)
print("TEST 3: New API Endpoint (api.acleddata.com)")
print("=" * 80)

if not ACLED_API_KEY:
    print("⚠️  ACLED_API_KEY not set - skipping v3 API test")
    print("\nTo get your API key:")
    print("1. Login to https://acleddata.com/dashboard/")
    print("2. Go to 'API Access' or 'My Account'")
    print("3. Copy your API key")
    print("4. Run: railway variables --set ACLED_API_KEY='your_key_here'")
else:
    # Try multiple v3 endpoint variations
    v3_endpoints = [
        "https://api.acleddata.com/acled/read",
        "https://api.acleddata.com/v3/data/export",
        "https://api.acleddata.com/data/export"
    ]
    
    for endpoint in v3_endpoints:
        print(f"\nTrying: {endpoint}")
        try:
            response = requests.get(
                endpoint,
                params={
                    "key": ACLED_API_KEY,
                    "email": ACLED_EMAIL,
                    "country": test_country,
                    "event_date": test_date,
                    "limit": 5
                },
                timeout=10
            )
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                events = data.get("data", []) if isinstance(data, dict) else data
                print(f"✅ V3 API WORKS at {endpoint}")
                print(f"Events: {len(events)}")
                if events:
                    print(f"Sample event: {events[0].get('event_type', 'N/A')}")
                break
            else:
                print(f"❌ Failed: {response.text[:200]}")
                
        except requests.exceptions.Timeout:
            print(f"⏱️  Timeout (endpoint may not exist)")
        except Exception as e:
            print(f"❌ Error: {e}")

# Test 4: Try without authentication (public endpoint)
print("\n" + "=" * 80)
print("TEST 4: Public Export Endpoint (No Auth)")
print("=" * 80)

try:
    # ACLED sometimes has public export endpoints
    response = requests.get(
        "https://acleddata.com/data-export-tool/",
        timeout=5
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✅ Public page accessible (but likely requires form submission)")
    else:
        print("❌ Public export not accessible")
except Exception as e:
    print(f"❌ Error: {e}")

# Summary
print("\n" + "=" * 80)
print("SUMMARY & RECOMMENDATIONS")
print("=" * 80)
print("""
Based on testing above:

1. If OAuth works but OLD API returns 403:
   → You need to register for API access at ACLED dashboard
   → Free accounts can authenticate but not access data API

2. If you have ACLED_API_KEY:
   → Set it with: railway variables --set ACLED_API_KEY='your_key'
   → Use the v3 endpoint that worked above

3. Alternative - Manual Data Export:
   → Go to https://acleddata.com/data-export-tool/
   → Export CSV manually for your countries
   → Upload to system (one-time backfill)

4. Contact ACLED Support:
   → Email: support@acleddata.com
   → Request: API data access for your account
   → Mention: Building threat intelligence system
""")

print("\n" + "=" * 80)
