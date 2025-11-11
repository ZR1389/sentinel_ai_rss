#!/usr/bin/env python3
"""
Test script to debug the /api/sentinel-chat endpoint with proper authentication
"""

import requests
import json
import os
import sys

# Add the parent directory to Python path to import auth_utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from auth_utils import create_access_token
except ImportError as e:
    print(f"Failed to import auth_utils: {e}")
    sys.exit(1)

def test_chat_endpoint():
    """Test the /api/sentinel-chat endpoint with a valid JWT token"""
    
    # Generate a test JWT token
    test_email = "test@example.com"
    test_plan = "FREE"
    
    try:
        token = create_access_token(test_email, test_plan)
        print(f"Generated JWT token for {test_email}: {token[:50]}...")
    except Exception as e:
        print(f"Failed to generate JWT token: {e}")
        return False
    
    # Prepare the request
    url = "http://localhost:8080/api/sentinel-chat"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "query": "What are the latest security threats?",
        "profile_data": {"location": "US", "industry": "Technology"},
        "input_data": {"priority": "high"}
    }
    
    print(f"Testing endpoint: {url}")
    print(f"Headers: {headers}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"\nResponse status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        try:
            response_data = response.json()
            print(f"Response body: {json.dumps(response_data, indent=2)}")
        except json.JSONDecodeError:
            print(f"Response body (raw): {response.text}")
        
        return response.status_code == 202 or response.status_code == 200
        
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing /api/sentinel-chat endpoint...")
    success = test_chat_endpoint()
    print(f"\nTest {'PASSED' if success else 'FAILED'}")
    sys.exit(0 if success else 1)
