#!/usr/bin/env python3
"""
Test LLM Router Provider Priority
Tests the new paid provider order: Grok → OpenAI → Moonshot → DeepSeek
"""
import os
import sys
import time
import logging

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Add parent directories to path for imports  
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from llm_router import route_llm

def test_provider_priority():
    """Test the LLM provider priority order"""
    print("🧪 Testing LLM Provider Priority Order...")
    print("=" * 60)
    
    # Create simple test message
    test_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, respond with just 'OK' and the name of your model/provider."}
    ]
    
    # Track usage counts
    usage_counts = {"deepseek": 0, "openai": 0, "grok": 0, "moonshot": 0, "none": 0}
    
    print("📋 Current Environment Settings:")
    print(f"   PRIMARY: {os.getenv('ADVISOR_PROVIDER_PRIMARY', 'undefined')}")
    print(f"   SECONDARY: {os.getenv('ADVISOR_PROVIDER_SECONDARY', 'undefined')}")
    print(f"   TERTIARY: {os.getenv('ADVISOR_PROVIDER_TERTIARY', 'undefined')}")
    print(f"   QUATERNARY: {os.getenv('ADVISOR_PROVIDER_QUATERNARY', 'undefined')}")
    print("")
    
    print("🚀 Testing General Routing (should prioritize Grok)...")
    start_time = time.time()
    
    try:
        response, provider = route_llm(test_messages, temperature=0.2, usage_counts=usage_counts)
        response_time = time.time() - start_time
        
        if response and provider != "none":
            print(f"✅ SUCCESS: Provider '{provider}' responded in {response_time:.2f}s")
            print(f"   Response: {response[:100]}{'...' if len(response) > 100 else ''}")
            print(f"   Expected: Grok (primary) - {'✅ CORRECT' if provider == 'grok' else '❌ UNEXPECTED'}")
        else:
            print(f"❌ FAILED: No valid response from any provider")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
    
    print("\n📊 Provider Usage Counts:")
    for provider, count in usage_counts.items():
        status = "✅" if count > 0 else "⚪"
        print(f"   {status} {provider.upper()}: {count}")
    
    # Test enrichment/search routing
    print("\n🔍 Testing Search/Enrichment Routing (should prioritize Grok)...")
    usage_counts_search = {"deepseek": 0, "openai": 0, "grok": 0, "moonshot": 0, "none": 0}
    
    start_time = time.time()
    try:
        response, provider = route_llm(test_messages, temperature=0.2, 
                                     usage_counts=usage_counts_search, task_type="enrichment")
        response_time = time.time() - start_time
        
        if response and provider != "none":
            print(f"✅ SUCCESS: Provider '{provider}' responded in {response_time:.2f}s")
            print(f"   Expected: Grok (primary enrichment) - {'✅ CORRECT' if provider == 'grok' else '❌ UNEXPECTED'}")
        else:
            print(f"❌ FAILED: No valid response from any provider")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
    
    print("\n📊 Search/Enrichment Usage Counts:")
    for provider, count in usage_counts_search.items():
        status = "✅" if count > 0 else "⚪"
        print(f"   {status} {provider.upper()}: {count}")

def test_fallback_behavior():
    """Test what happens if primary providers fail"""
    print("\n" + "=" * 60)
    print("🔄 Testing Fallback Behavior...")
    print("   (This requires manual testing - disable API keys to test)")
    
    # Show current API key status
    print("\n🔑 API Key Status:")
    providers = [
        ("XAI", "XAI_API_KEY"),
        ("OPENAI", "OPENAI_API_KEY"),
        ("MOONSHOT", "MOONSHOT_API_KEY"), 
        ("DEEPSEEK", "DEEPSEEK_API_KEY")
    ]
    
    for name, env_var in providers:
        key = os.getenv(env_var, "")
        status = "✅ SET" if key and len(key) > 10 else "❌ MISSING"
        masked_key = key[:8] + "..." + key[-4:] if len(key) > 12 else "MISSING"
        print(f"   {status} {name}: {masked_key}")

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 Sentinel AI LLM Router Priority Test")
    print("Testing provider order: Grok → OpenAI → Moonshot → DeepSeek")
    
    test_provider_priority()
    test_fallback_behavior()
    
    print("\n" + "=" * 60)
    print("✅ LLM Router Priority Test Complete!")
    print("📝 Expected behavior: Paid providers (Grok, OpenAI, Moonshot) should be")
    print("   prioritized before free fallback (DeepSeek)")
