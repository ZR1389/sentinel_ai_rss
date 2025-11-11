#!/usr/bin/env python3
"""
Debug the 500 error from /api/sentinel-chat endpoint
"""
import os
import sys
import json
import logging
import traceback
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_chat_handler_direct():
    """Test calling handle_user_query directly to isolate the issue"""
    print("🧪 Testing Chat Handler Direct Call...")
    print("=" * 60)
    
    try:
        from chat_handler import handle_user_query
        print("✅ handle_user_query imported successfully")
        
        # Test a simple call
        result = handle_user_query(
            message="Test security query",
            email="debug.test@example.com"
        )
        
        print(f"✅ Direct call successful: {type(result)}")
        print(f"   Result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
        
    except Exception as e:
        print(f"❌ Direct call failed: {e}")
        print(f"   Traceback: {traceback.format_exc()}")

def test_background_job():
    """Test the background job mechanism"""
    print("\n🧪 Testing Background Job Mechanism...")
    print("=" * 60)
    
    try:
        from chat_handler import start_background_job, handle_user_query, get_background_status
        print("✅ Background functions imported successfully")
        
        # Test starting a background job
        session_id = "debug-test-123"
        print(f"   Starting background job: {session_id}")
        
        start_background_job(
            session_id,
            handle_user_query,
            "Debug test query",  # message
            "debug.test@example.com",  # email
            body={"profile_data": {"role": "Debug"}}
        )
        
        print("✅ Background job started successfully")
        
        # Check status immediately
        status = get_background_status(session_id)
        job_status = status.get("job", {}).get("status", "unknown")
        print(f"   Initial status: {job_status}")
        
    except Exception as e:
        print(f"❌ Background job test failed: {e}")
        print(f"   Traceback: {traceback.format_exc()}")

def test_main_imports():
    """Test the imports used in main.py"""
    print("\n🧪 Testing Main.py Imports...")
    print("=" * 60)
    
    try:
        # Test the imports that main.py would use
        from chat_handler import get_background_status, start_background_job, handle_user_query
        print("✅ All main.py imports successful")
        
        # Test if all functions are callable
        if callable(get_background_status):
            print("✅ get_background_status is callable")
        else:
            print("❌ get_background_status is not callable")
            
        if callable(start_background_job):
            print("✅ start_background_job is callable")
        else:
            print("❌ start_background_job is not callable")
            
        if callable(handle_user_query):
            print("✅ handle_user_query is callable")
        else:
            print("❌ handle_user_query is not callable")
            
    except Exception as e:
        print(f"❌ Main.py imports failed: {e}")
        print(f"   Traceback: {traceback.format_exc()}")

def test_timing_variables():
    """Test if our timing enhancements are causing issues"""
    print("\n🧪 Testing Timing Variables...")
    print("=" * 60)
    
    try:
        import time
        
        # Simulate the timing setup from handle_user_query
        overall_start = time.perf_counter()
        setup_start = time.perf_counter()
        
        # Initialize timing variables with defaults (like our fix)
        setup_elapsed = 0.0
        db_elapsed = 0.0
        preprocessing_elapsed = 0.0  
        advisor_elapsed = 0.0
        
        # Test calculating elapsed times
        setup_elapsed = time.perf_counter() - setup_start
        overall_elapsed = time.perf_counter() - overall_start
        
        print(f"✅ Timing calculations successful:")
        print(f"   Setup: {setup_elapsed:.3f}s")
        print(f"   DB: {db_elapsed:.3f}s") 
        print(f"   Preprocessing: {preprocessing_elapsed:.3f}s")
        print(f"   Advisor: {advisor_elapsed:.3f}s")
        print(f"   Total: {overall_elapsed:.3f}s")
        
    except Exception as e:
        print(f"❌ Timing test failed: {e}")
        print(f"   Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    print("🐛 Sentinel AI Chat Backend Debug")
    print("Investigating the 500 error from /api/sentinel-chat")
    
    test_main_imports()
    test_timing_variables()
    test_chat_handler_direct()
    test_background_job()
    
    print("\n" + "=" * 60)
    print("✅ Debug Analysis Complete!")
    print("📝 Check the results above to identify the 500 error cause")
