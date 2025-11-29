#!/usr/bin/env python3
"""
Test Advisor with New LLM Provider Priority
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

from api.advisor import render_advisory, get_llm_routing_stats

def test_advisor_with_new_priority():
    """Test that the advisor uses the new LLM provider priority"""
    print("🧪 Testing Advisor with New LLM Provider Priority...")
    print("=" * 60)
    
    # Create a simple mock alert for testing
    mock_alert = {
        "title": "Test Security Alert",
        "summary": "This is a test security alert for priority testing.",
        "city": "New York",
        "country": "United States",
        "link": "https://example.com/alert",
        "threat_level": "moderate",
        "category": "malware"
    }
    
    print("📋 Expected Provider Order: Grok → OpenAI → Moonshot → DeepSeek")
    print(f"📊 Usage Counts Before: {get_llm_routing_stats()}")
    print("")
    
    print("🚀 Testing render_advisory() with new priority...")
    start_time = time.time()
    
    try:
        advisory = render_advisory(
            alert=mock_alert,
            user_message="Generate a brief security advisory for this alert",
            profile_data={
                "role": "IT Administrator",
                "organization_type": "enterprise",
                "industry": "technology"
            }
        )
        
        response_time = time.time() - start_time
        
        if advisory:
            print(f"✅ SUCCESS: Advisor responded in {response_time:.2f}s")
            print(f"   Advisory length: {len(advisory)} characters")
            
            # Look for provider in advisory (some providers include their name)
            providers_mentioned = []
            for provider in ["grok", "openai", "moonshot", "deepseek"]:
                if provider.lower() in advisory.lower():
                    providers_mentioned.append(provider)
            
            if providers_mentioned:
                print(f"   Provider indicators: {providers_mentioned}")
        else:
            print(f"❌ FAILED: No advisory generated")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n📊 Usage Counts After: {get_llm_routing_stats()}")
    
    # Check which provider was actually used
    routing_stats = get_llm_routing_stats()
    usage_counts = routing_stats.get('usage_counts', {})
    used_providers = [provider for provider, count in usage_counts.items() if count > 0 and provider != "none"]
    if used_providers:
        # Find the most recently used provider (assume last one used)
        primary_provider = None
        for provider in ["grok", "openai", "moonshot", "deepseek"]:
            if usage_counts.get(provider, 0) > 0:
                primary_provider = provider
                break
                
        if primary_provider:
            print(f"🎯 Primary Provider Used: {primary_provider.upper()}")
            expected_order = ["grok", "openai", "moonshot", "deepseek"]
            
            if primary_provider in expected_order:
                position = expected_order.index(primary_provider) + 1
                if position == 1:
                    print(f"   ✅ PERFECT: Using primary paid provider (Grok)")
                elif position <= 3:
                    print(f"   ✅ GOOD: Using paid provider #{position} ({primary_provider.upper()})")
                else:
                    print(f"   ⚠️  FALLBACK: Using free provider (DeepSeek)")
            else:
                print(f"   ❌ UNEXPECTED: Unknown provider used")
        else:
            print(f"   ❌ FAILED: No provider detected")
    else:
        print(f"   ❌ FAILED: No provider responded successfully")

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 Sentinel AI Advisor LLM Priority Test")
    print("Testing that advisor uses new priority: Grok → OpenAI → Moonshot → DeepSeek")
    
    test_advisor_with_new_priority()
    
    print("\n" + "=" * 60)
    print("✅ Advisor LLM Priority Test Complete!")
