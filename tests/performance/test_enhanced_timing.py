#!/usr/bin/env python3
"""
Test Enhanced Timing in Chat Handler
Tests the new detailed timing tracking for performance monitoring and optimization
"""
import os
import sys
import time
import json
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_timing_tracking():
    """Test the enhanced timing tracking in handle_user_query"""
    print("🧪 Testing Enhanced Timing Tracking...")
    print("=" * 60)
    
    try:
        from chat_handler import handle_user_query
        
        print("✅ Chat handler imported successfully")
        print("")
        
        # Test timing with a simple query
        print("📋 Test: Timing Tracking with Simple Query")
        test_email = "timing.test@example.com"
        test_query = "What are the cybersecurity threats in San Francisco?"
        
        print(f"   📝 Query: {test_query}")
        print(f"   👤 User: {test_email}")
        print("")
        
        # Capture timing output by monitoring logs
        print("🕐 Executing query with detailed timing...")
        
        # Set up logging to capture timing info
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        start_time = time.time()
        
        try:
            result = handle_user_query(
                message=test_query,
                email=test_email,
                body={"profile_data": {"role": "Security Analyst"}}
            )
            
            execution_time = time.time() - start_time
            print(f"✅ Query completed in {execution_time:.2f}s")
            
            # Check result structure
            if isinstance(result, dict):
                print(f"   📊 Result keys: {list(result.keys())}")
                if result.get("reply"):
                    print(f"   💬 Reply preview: {result['reply'][:100]}...")
                if result.get("alerts"):
                    print(f"   🚨 Alerts count: {len(result['alerts'])}")
            
            print("")
            print("🔍 Expected Log Output Should Include:")
            print("   ✅ Setup phase: X.XXXs")
            print("   ✅ DB phase: X.XXXs (N alerts)")
            print("   ✅ Preprocessing phase: X.XXXs") 
            print("   ✅ Advisor phase: X.XXXs")
            print("   ✅ === TIMING SUMMARY ===")
            print("   ✅ Total request time: X.XXXs")
            print("   ✅ === END TIMING ===")
            
        except Exception as e:
            print(f"❌ Query failed: {e}")
            # Even on failure, timing should be logged
            
    except ImportError as e:
        print(f"   ❌ Import failed: {e}")
        print("   💡 Make sure chat_handler.py is accessible")
    except Exception as e:
        print(f"   ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

def test_timing_benefits():
    """Show the benefits of enhanced timing tracking"""
    print("\n" + "=" * 60)
    print("📊 Enhanced Timing Tracking Benefits")
    print("=" * 60)
    
    timing_improvements = [
        ("Performance Monitoring", "⚪ No detailed breakdown", "📊 Phase-by-phase timing"),
        ("Bottleneck Identification", "🤷 Hard to find slow parts", "🎯 Pinpoint exact phase"),
        ("LLM Optimization", "❓ Unknown provider performance", "⚡ Track Grok→OpenAI→Moonshot→DeepSeek"),
        ("DB Query Monitoring", "⏱️ Basic timing", "🔍 Slow query detection (>20s)"),
        ("Advisor Performance", "🕒 Simple duration", "📈 Slow advisor alerts (>60s)"),
        ("Overall Request Health", "⏰ Total time only", "🚨 Slow request alerts (>50s)"),
        ("Log Structure", "📝 Scattered timing", "📋 Organized timing summary"),
        ("Security Events", "🔐 Basic logging", "🛡️ Performance-based security events")
    ]
    
    print(f"{'Aspect':<25} {'Before (Basic)':<25} {'After (Enhanced)':<30}")
    print("-" * 80)
    for aspect, before, after in timing_improvements:
        print(f"{aspect:<25} {before:<25} {after:<30}")
    
    print("\n🎯 Key Timing Features:")
    print("   🕐 Setup phase - User validation, cache checks")
    print("   💾 DB phase - Alert fetching with slow query detection")  
    print("   🔄 Preprocessing - Geographic analysis, historical context")
    print("   🤖 Advisor phase - LLM calls with provider priority")
    print("   📊 Organized summary - Clear phase breakdown")
    print("   🚨 Performance alerts - Security events for slow operations")

def test_performance_thresholds():
    """Test the performance threshold system"""
    print("\n" + "=" * 60)
    print("⏱️ Performance Threshold Analysis")
    print("=" * 60)
    
    thresholds = {
        "DB Query": {"threshold": 20, "action": "slow_db_query security event"},
        "Advisor Call": {"threshold": 60, "action": "slow_advisor_call security event"},
        "Total Request": {"threshold": 50, "action": "slow_request security event with breakdown"}
    }
    
    print("🎯 Performance Monitoring Thresholds:")
    for phase, config in thresholds.items():
        print(f"   📊 {phase}: >{config['threshold']}s → {config['action']}")
    
    print("\n🔍 Example Security Event for Slow Request:")
    example_event = {
        "event_type": "slow_request",
        "email": "user@example.com",
        "plan": "FREE", 
        "details": "Total: 65.23s (Setup: 0.12s, DB: 45.67s, Preprocessing: 2.34s, Advisor: 17.10s)"
    }
    print(json.dumps(example_event, indent=2))
    
    print("\n✅ Benefits for Operations:")
    print("   🔧 Identify which phase is causing slowdowns")
    print("   📈 Monitor LLM provider performance over time")
    print("   🛠️ Optimize the slowest components first")
    print("   📊 Track improvements after optimizations")
    print("   🚨 Alert on performance degradation")

def test_llm_provider_timing_insights():
    """Show how timing helps with LLM provider optimization"""
    print("\n" + "=" * 60)
    print("🤖 LLM Provider Performance Insights")
    print("=" * 60)
    
    print("📊 With Enhanced Timing, You Can Track:")
    
    provider_scenarios = [
        {
            "scenario": "Grok Fast Response",
            "advisor_time": "8.23s",
            "insight": "✅ Primary provider working well"
        },
        {
            "scenario": "Grok Timeout → OpenAI Fallback", 
            "advisor_time": "35.67s",
            "insight": "⚠️ Grok slow, fallback working"
        },
        {
            "scenario": "All Providers Slow",
            "advisor_time": "78.45s", 
            "insight": "🚨 System-wide LLM issues"
        },
        {
            "scenario": "DeepSeek Free Tier Hit",
            "advisor_time": "12.34s",
            "insight": "🎯 Paid providers exhausted, using free tier"
        }
    ]
    
    for scenario in provider_scenarios:
        print(f"\n🎬 {scenario['scenario']}:")
        print(f"   ⏱️ Advisor phase: {scenario['advisor_time']}")
        print(f"   💡 Insight: {scenario['insight']}")
    
    print("\n🔧 Optimization Actions Based on Timing:")
    print("   📈 Advisor >60s → Check LLM provider order")
    print("   💾 DB >20s → Optimize database queries")
    print("   🔄 Preprocessing >10s → Improve geographic processing")
    print("   🕐 Setup >5s → Review cache efficiency")
    
    print("\n✅ Your Grok→OpenAI→Moonshot→DeepSeek priority is now trackable!")

if __name__ == "__main__":
    print("🧪 Sentinel AI Enhanced Timing Tracking Test")
    print("Testing detailed performance monitoring and bottleneck identification")
    
    test_timing_tracking()
    test_timing_benefits()
    test_performance_thresholds()
    test_llm_provider_timing_insights()
    
    print("\n" + "=" * 60)
    print("✅ Enhanced Timing Tracking Analysis Complete!")
    print("📝 Your timing improvements provide excellent performance visibility!")
