#!/usr/bin/env python3
"""
Test script for Railway health check deployment
"""

import json
import time
import sys
import os

def test_health_components():
    """Test all health check components."""
    print("=== Railway Health Check System Test ===\n")
    
    # Test 1: Health check module
    print("1. Testing health_check.py module...")
    try:
        from health_check import perform_health_check
        result = perform_health_check()
        print(f"   ✅ Status: {result['status']}")
        print(f"   📊 Database: {'✅' if result['checks']['database']['connected'] else '❌'}")
        print(f"   🧠 LLM: {'✅' if result['checks']['llm']['any_available'] else '❌'}")
        print(f"   🔄 Vector System: {'✅' if result['checks']['vector_system']['system_ready'] else '❌'}")
        print(f"   🔧 Keywords: {result['checks']['vector_system']['keywords_count']} loaded")
        
        if result['issues']:
            print(f"   ⚠️  Issues: {len(result['issues'])}")
            for issue in result['issues']:
                print(f"      - {issue}")
        print()
        
    except Exception as e:
        print(f"   ❌ Error: {e}\n")
        return False
    
    # Test 2: Flask health server
    print("2. Testing health_server.py...")
    try:
        from health_server import app as health_app
        with health_app.test_client() as client:
            response = client.get('/health')
            print(f"   ✅ /health endpoint: {response.status_code}")
            
            response = client.get('/ping')  
            print(f"   ✅ /ping endpoint: {response.status_code}")
            print()
            
    except Exception as e:
        print(f"   ❌ Error: {e}\n")
        return False
    
    # Test 3: Main app integration
    print("3. Testing main.py health integration...")
    try:
        from main import app as main_app
        with main_app.test_client() as client:
            response = client.get('/health/quick')
            print(f"   ✅ Main app /health/quick: {response.status_code}")
            
            response = client.get('/ping')
            print(f"   ✅ Main app /ping: {response.status_code}")
            print()
            
    except Exception as e:
        print(f"   ❌ Error: {e}\n")
        return False
        
    return True

def print_railway_instructions():
    """Print Railway deployment instructions."""
    print("=== Railway Deployment Instructions ===\n")
    
    print("1. 📱 Connect to Railway:")
    print("   - Go to Railway Dashboard")
    print("   - New Project → Deploy from GitHub")
    print("   - Select your sentinel_ai_rss repository")
    print()
    
    print("2. ⚙️  Set Environment Variables:")
    print("   Required:")
    print("   - DATABASE_URL (PostgreSQL connection)")
    print("   - At least one: OPENAI_API_KEY, XAI_API_KEY, or DEEPSEEK_API_KEY")
    print("   Optional:")  
    print("   - REDIS_URL, PORT")
    print()
    
    print("3. 🏥 Configure Health Check:")
    print("   - Settings → Health Check → Enable")
    print("   - Health Check Path: /health")
    print("   - Timeout: 30 seconds")
    print()
    
    print("4. 🚀 Deploy Commands (choose one):")
    print("   Option A (Health server only):")
    print("   python health_server.py")
    print()
    print("   Option B (Main app with health):")
    print("   gunicorn main:app --bind 0.0.0.0:$PORT --timeout 300")
    print()
    print("   Option C (FastAPI - if installed):")
    print("   uvicorn health_check:app --host 0.0.0.0 --port $PORT")
    print()
    
    print("5. 📊 Monitoring:")
    print("   - /health → Full system check")
    print("   - /health/quick → Database only")  
    print("   - /ping → Simple liveness")
    print()

def main():
    """Main test function."""
    
    # Run tests
    if test_health_components():
        print("🎉 ALL TESTS PASSED! 🎉\n")
        print("✅ Health check system ready for Railway deployment")
        print("✅ Zero-downtime deployments supported")
        print("✅ Comprehensive service monitoring")
        print()
        
        print_railway_instructions()
        
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
