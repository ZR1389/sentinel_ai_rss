#!/usr/bin/env python3
"""
Test the /api/sentinel-chat endpoint with a verified user to see if we can reproduce the 500 error.
"""

import os
import json
import requests
import sys

try:
    from auth_utils import create_access_token
    from db_utils import execute
except ImportError as e:
    print(f"Failed to import auth_utils: {e}")
    sys.exit(1)

def create_verified_user_and_test():
    """Create a verified user and test the endpoint"""
    
    # Test configuration  
    base_url = "http://localhost:8080"
    test_email = "verified@example.com"
    test_plan = "FREE"
    
    try:
        # Step 1: Create user in database (if db is available)
        print("Creating verified user in database...")
        try:
            # Create user
            execute("""
                INSERT INTO users (email, plan, email_verified, password_hash)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                email_verified = EXCLUDED.email_verified
            """, (test_email, test_plan, True, 'dummy_hash'))
            print(f"User {test_email} created/updated as verified")
        except Exception as e:
            print(f"Database setup failed (this is expected if no DB): {e}")
        
        # Step 2: Generate valid JWT token
        print("Generating JWT token...")
        token = create_access_token(test_email, test_plan)
        print(f"Generated JWT token: {token[:50]}...")
        
        # Step 3: Test the endpoint
        print(f"Testing endpoint: {base_url}/api/sentinel-chat")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "query": "What are the latest security threats in my industry?",
            "profile_data": {
                "location": "US", 
                "industry": "Technology",
                "company_size": "Medium"
            },
            "input_data": {
                "priority": "high",
                "timeframe": "recent"
            }
        }
        
        print(f"Headers: {headers}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        print()
        
        response = requests.post(f"{base_url}/api/sentinel-chat", headers=headers, json=payload)
        
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        try:
            response_data = response.json()
            print(f"Response body: {json.dumps(response_data, indent=2)}")
        except:
            print(f"Response body (raw): {response.text}")
        
        if response.status_code == 500:
            print("\n🚨 500 ERROR REPRODUCED! Check backend logs for details.")
            return False
        elif response.status_code == 202:
            print("\n✅ SUCCESS! Backend accepted the request.")
            return True
        else:
            print(f"\n📝 Other response code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Testing /api/sentinel-chat endpoint with verified user...")
    print("=" * 60)
    
    success = create_verified_user_and_test()
    
    if success:
        print("Test PASSED")
        sys.exit(0)
    else:
        print("Test FAILED")
        sys.exit(1)
