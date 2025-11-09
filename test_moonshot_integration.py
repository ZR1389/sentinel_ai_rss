#!/usr/bin/env python3
"""
Test script for Kimi Moonshot integration
"""

import os
import sys
sys.path.append('/Users/zikarakita/Documents/sentinel_ai_rss')

from moonshot_client import test_moonshot_connection
from llm_router import route_llm

def test_integration():
    """Test the full LLM router integration with Moonshot"""
    
    print("=== Kimi Moonshot Integration Test ===\n")
    
    # Test 1: Direct client test
    print("1. Testing Moonshot client directly...")
    if test_moonshot_connection():
        print("   ✅ Direct client test passed\n")
    else:
        print("   ❌ Direct client test failed\n")
        return False
    
    # Test 2: LLM Router integration
    print("2. Testing LLM Router integration...")
    
    test_messages = [
        {"role": "system", "content": "You are a security analyst. Respond concisely."},
        {"role": "user", "content": "Analyze this threat: 'Suspicious login attempt from foreign IP address'. Provide a brief threat assessment."}
    ]
    
    # Force Moonshot as primary to test routing
    os.environ["ADVISOR_PROVIDER_PRIMARY"] = "moonshot"
    
    try:
        result, model_used = route_llm(test_messages, temperature=0.3)
        
        if result and model_used == "moonshot":
            print(f"   ✅ Router test passed")
            print(f"   🤖 Model used: {model_used}")
            print(f"   📝 Response: {result[:100]}...")
        else:
            print(f"   ❌ Router test failed - Model: {model_used}, Result: {bool(result)}")
            return False
    except Exception as e:
        print(f"   ❌ Router test error: {e}")
        return False
    
    print("\n=== Integration test completed successfully! ===")
    print("\n📋 Next steps:")
    print("1. Add MOONSHOT_API_KEY to your .env file")
    print("2. Optionally set MOONSHOT_MODEL (default: moonshot-v1-8k)")
    print("3. Configure ADVISOR_PROVIDER_QUATERNARY=moonshot in .env")
    print("4. Your LLM fallback order: DeepSeek → OpenAI → Grok → Moonshot")
    
    return True

if __name__ == "__main__":
    test_integration()
