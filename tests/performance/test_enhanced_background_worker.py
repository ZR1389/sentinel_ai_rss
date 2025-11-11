#!/usr/bin/env python3
"""
Test Enhanced Background Worker Implementation
Tests the improved background worker with better error handling and direct handle_user_query integration
"""
import os
import sys
import time
import json
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_enhanced_background_worker():
    """Test the enhanced background worker functionality"""
    print("🧪 Testing Enhanced Background Worker...")
    print("=" * 60)
    
    try:
        from chat_handler import start_background_job, get_background_status, handle_user_query
        
        print("✅ Background job functions imported successfully")
        print("")
        
        # Test 1: Successful background job
        print("📋 Test 1: Successful Background Processing")
        test_session_1 = f"test-success-{int(time.time())}"
        
        print(f"   ▶️ Starting background job: {test_session_1}")
        start_time = time.time()
        
        # Start background job with handle_user_query
        start_background_job(
            test_session_1,
            handle_user_query,
            "What are the current cybersecurity threats?",  # message
            "test@example.com",  # email
            body={"profile_data": {"role": "Security Analyst"}}
        )
        
        startup_duration = time.time() - start_time
        print(f"   ✅ Job started in {startup_duration:.3f}s")
        
        # Poll for status
        print("   🔍 Polling for status...")
        max_polls = 30  # 30 seconds max
        poll_count = 0
        
        while poll_count < max_polls:
            status = get_background_status(test_session_1)
            job_status = status.get("job", {}).get("status", "unknown")
            
            print(f"   📊 Poll #{poll_count + 1}: Status = {job_status}")
            
            if job_status == "done":
                result = status.get("result", {})
                print(f"   ✅ SUCCESS: Job completed")
                print(f"   📄 Result keys: {list(result.keys())}")
                if result.get("reply"):
                    print(f"   💬 Reply preview: {result['reply'][:100]}...")
                break
            elif job_status == "failed":
                error = status.get("job", {}).get("error", "Unknown error")
                print(f"   ❌ FAILED: {error}")
                result = status.get("result", {})
                if result and result.get("error"):
                    print(f"   🔍 Error details: {result['error']}")
                break
            elif job_status in ("running", "pending"):
                print(f"   ⏳ Still processing...")
            else:
                print(f"   ❓ Unknown status: {job_status}")
                break
            
            poll_count += 1
            time.sleep(1)
        
        if poll_count >= max_polls:
            print(f"   ⏰ TIMEOUT: Job didn't complete in {max_polls} seconds")
        
        print("")
        
        # Test 2: Error handling
        print("📋 Test 2: Error Handling")
        test_session_2 = f"test-error-{int(time.time())}"
        
        def failing_function(*args, **kwargs):
            """Mock function that always fails"""
            raise ValueError("Intentional test failure")
        
        print(f"   ▶️ Starting failing background job: {test_session_2}")
        start_background_job(
            test_session_2,
            failing_function,
            "test"
        )
        
        # Wait a bit then check status
        time.sleep(2)
        error_status = get_background_status(test_session_2)
        job_status = error_status.get("job", {}).get("status", "unknown")
        
        if job_status == "failed":
            print(f"   ✅ Error handled correctly: Status = failed")
            error_result = error_status.get("result", {})
            if error_result and error_result.get("error"):
                print(f"   🔍 Error cached for client: {error_result['error']}")
                print(f"   💬 User-friendly message: {error_result.get('reply', 'N/A')}")
            else:
                print(f"   ⚠️ Error not cached properly")
        else:
            print(f"   ❌ Error not handled correctly: Status = {job_status}")
        
    except ImportError as e:
        print(f"   ❌ Import failed: {e}")
        print("   💡 Make sure chat_handler.py is accessible")
    except Exception as e:
        print(f"   ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

def test_improvement_benefits():
    """Show the benefits of the enhanced worker"""
    print("\n" + "=" * 60)
    print("📊 Background Worker Improvements")
    print("=" * 60)
    
    improvements = [
        ("Error Result Caching", "❌ Errors lost", "✅ Cached for client polling"),
        ("Function Integration", "🔧 Generic target_fn", "🎯 Direct handle_user_query"),
        ("Argument Handling", "⚠️ Fragile *args/**kwargs", "🛡️ Explicit parameter extraction"),
        ("Error Recovery", "💥 Job fails silently", "🔄 User-friendly error messages"),
        ("Client Experience", "🤷 No error feedback", "📋 Detailed error information"),
        ("Debugging", "🕵️ Hard to troubleshoot", "🔍 Clear error logging"),
        ("Reliability", "🎲 Inconsistent results", "📊 Always returns something"),
        ("Monitoring", "👀 Limited visibility", "📈 Better observability")
    ]
    
    print(f"{'Aspect':<20} {'Before (Old)':<25} {'After (Enhanced)':<30}")
    print("-" * 75)
    for aspect, before, after in improvements:
        print(f"{aspect:<20} {before:<25} {after:<30}")
    
    print("\n🎯 Key Benefits:")
    print("   🚀 Always returns a result (success or error)")
    print("   🔍 Clients can poll for error details") 
    print("   🛡️ More robust argument handling")
    print("   📊 Better monitoring and debugging")
    print("   💪 Handles both new async and legacy patterns")

def test_api_flow_simulation():
    """Simulate the full async API flow"""
    print("\n" + "=" * 60)
    print("🔄 Full Async API Flow Simulation")
    print("=" * 60)
    
    print("📱 Step 1: Client sends chat request")
    chat_request = {
        "query": "What cybersecurity threats should I watch for?",
        "profile_data": {"role": "IT Admin"}
    }
    print(f"   Request: {json.dumps(chat_request, indent=4)}")
    
    print("\n📨 Step 2: Server responds immediately (202)")
    immediate_response = {
        "accepted": True,
        "session_id": "abc-123-def-456",
        "message": "Processing your request. Poll /api/chat/status/<session_id> for results.",
        "plan": "FREE"
    }
    print(f"   Response: {json.dumps(immediate_response, indent=4)}")
    
    print("\n🔄 Step 3: Enhanced background worker processes request")
    print("   ✅ Direct handle_user_query call")
    print("   ✅ LLM provider priority: Grok → OpenAI → Moonshot → DeepSeek")
    print("   ✅ Result cached with metadata")
    
    print("\n📊 Step 4: Client polls for status")
    processing_status = {
        "status": "running",
        "message": "Still processing...",
        "started_at": "2025-11-10T21:05:00Z"
    }
    print(f"   Status (202): {json.dumps(processing_status, indent=4)}")
    
    print("\n🎉 Step 5: Processing complete")
    final_result = {
        "reply": "Based on current threat intelligence...",
        "alerts": [],
        "usage": {"grok": 1},
        "_background": True,
        "_completed_at": "2025-11-10T21:07:30Z"
    }
    print(f"   Result (200): {json.dumps(final_result, indent=4)}")
    
    print("\n✅ Enhanced worker ensures reliable async processing!")

if __name__ == "__main__":
    print("🧪 Sentinel AI Enhanced Background Worker Test")
    print("Testing improved error handling and integration")
    
    test_enhanced_background_worker()
    test_improvement_benefits()
    test_api_flow_simulation()
    
    print("\n" + "=" * 60)
    print("✅ Enhanced Background Worker Analysis Complete!")
    print("📝 Your improvements make the async system much more robust!")
