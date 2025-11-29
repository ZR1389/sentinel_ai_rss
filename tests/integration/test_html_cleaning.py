#!/usr/bin/env python3
"""
Test HTML Content Cleaning

This test verifies that the RSS processor properly cleans HTML content
before displaying it on the frontend map.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

def test_html_cleaning():
    """Test the HTML content cleaning functionality"""
    print("🧪 Testing HTML Content Cleaning...")
    
    from services.rss_processor import _clean_html_content
    
    # Test case 1: Your actual problematic content
    dirty_content = """<p>Baghdad (IraqiNews.com) — The US-led Combined Joint Task Force &#8211; Operation Inherent Resolve (CJTF-OIR) has certified that Iraq&#8217;s security forces can officially conduct full combat-strike operations self-sufficiently, marking a significant step [&#8230;]</p> <p>The post <a href="https://www.iraqinews.com/iraq/u-s-led-coalition-certifies-iraqs-combat-strike-readiness/">U.S.-led coalition certifies Iraq's combat strike readiness</a> appeared first on <a href="https://www.iraqinews.com">Iraqi News</a>.</p>"""
    
    cleaned = _clean_html_content(dirty_content)
    print(f"Original: {dirty_content[:100]}...")
    print(f"Cleaned:  {cleaned}")
    print()
    
    # Test case 2: Common HTML entities
    test_cases = [
        {
            "input": "President says &#8220;peace&#8221; &amp; security are priorities.",
            "expected_contains": ["peace", "security", "&"],
            "expected_not_contains": ["&#8220;", "&amp;"]
        },
        {
            "input": "<p>Breaking news</p> <a href='#'>Read more</a>",
            "expected_contains": ["Breaking news"],
            "expected_not_contains": ["<p>", "</p>", "<a", "Read more"]
        },
        {
            "input": "Story continues [&#8230;] The post <a href='#'>Title</a> appeared first on Site.",
            "expected_contains": ["Story continues"],
            "expected_not_contains": ["[&#8230;]", "The post", "appeared first"]
        }
    ]
    
    all_passed = True
    
    for i, test in enumerate(test_cases):
        cleaned = _clean_html_content(test["input"])
        print(f"Test {i+1}:")
        print(f"  Input:   {test['input']}")
        print(f"  Cleaned: {cleaned}")
        
        # Check expected content
        for expected in test["expected_contains"]:
            if expected not in cleaned:
                print(f"  ❌ Missing expected content: '{expected}'")
                all_passed = False
            else:
                print(f"  ✅ Contains: '{expected}'")
        
        # Check unwanted content is removed
        for unwanted in test["expected_not_contains"]:
            if unwanted in cleaned:
                print(f"  ❌ Still contains unwanted: '{unwanted}'")
                all_passed = False
            else:
                print(f"  ✅ Removed: '{unwanted}'")
        print()
    
    if all_passed:
        print("🎉 All HTML cleaning tests passed!")
        return True
    else:
        print("❌ Some HTML cleaning tests failed!")
        return False

def test_rss_entry_processing():
    """Test that RSS entries are properly cleaned"""
    print("🧪 Testing RSS Entry Processing...")
    
    # Mock RSS entry data
    mock_entry = {
        "title": "U.S.-led coalition certifies Iraq&#8217;s combat strike readiness",
        "summary": """<p>Baghdad (IraqiNews.com) — The US-led Combined Joint Task Force &#8211; Operation Inherent Resolve (CJTF-OIR) has certified that Iraq&#8217;s security forces can officially conduct full combat-strike operations self-sufficiently, marking a significant step [&#8230;]</p> <p>The post <a href="https://www.iraqinews.com/iraq/u-s-led-coalition-certifies-iraqs-combat-strike-readiness/">U.S.-led coalition certifies Iraq's combat strike readiness</a> appeared first on <a href="https://www.iraqinews.com">Iraqi News</a>.</p>""",
        "link": "https://www.iraqinews.com/iraq/news",
        "published": "2025-11-09"
    }
    
    try:
        from services.rss_processor import _clean_html_content
        
        clean_title = _clean_html_content(mock_entry["title"])
        clean_summary = _clean_html_content(mock_entry["summary"])
        
        print(f"Original Title: {mock_entry['title']}")
        print(f"Clean Title:    {clean_title}")
        print()
        print(f"Original Summary: {mock_entry['summary'][:100]}...")
        print(f"Clean Summary:    {clean_summary}")
        print()
        
        # Verify cleaning
        if "&#" not in clean_title and "&#" not in clean_summary:
            print("✅ HTML entities properly decoded")
        else:
            print("❌ HTML entities still present")
            return False
            
        if "<p>" not in clean_summary and "</p>" not in clean_summary:
            print("✅ HTML tags properly removed")
        else:
            print("❌ HTML tags still present")
            return False
            
        if "appeared first on" not in clean_summary:
            print("✅ RSS footer content removed")
        else:
            print("❌ RSS footer still present")
            return False
            
        print("🎉 RSS entry processing test passed!")
        return True
        
    except Exception as e:
        print(f"❌ RSS entry processing test failed: {e}")
        return False

def main():
    """Run all HTML cleaning tests"""
    print("🧪 HTML Content Cleaning Test Suite")
    print("=" * 50)
    
    tests = [
        ("HTML Content Cleaning", test_html_cleaning),
        ("RSS Entry Processing", test_rss_entry_processing),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            if test_func():
                print(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                print(f"❌ {test_name}: FAILED")
                failed += 1
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"🏁 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All HTML cleaning tests passed! Your frontend will now show clean content.")
        return True
    else:
        print("⚠️  Some HTML cleaning tests failed. Check the output above for details.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
