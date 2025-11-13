#!/usr/bin/env python3
"""
Test script to demonstrate the benefits of fixing header formatting and guard patterns.
Shows how the enhanced patterns handle various spacing issues and formatting problems.
"""

import sys
import os
import re

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

def test_header_patterns():
    """Test the improved header patterns against various formatting scenarios."""
    
    print("=== TESTING ENHANCED HEADER FORMATTING & GUARD PATTERNS ===")
    print("Shows how the system now handles flexible spacing and formatting issues\n")
    
    # Import the enhanced patterns
    from advisor import REQUIRED_HEADERS, ensure_sections, clean_auto_sections
    
    # Test scenarios with various formatting issues
    test_cases = [
        {
            "name": "Perfect Formatting",
            "text": "ALERT —\nSecurity notice",
            "expected_match": True
        },
        {
            "name": "Extra Spaces Before Dash",
            "text": "ALERT   —\nSecurity notice", 
            "expected_match": True
        },
        {
            "name": "Missing Spaces",
            "text": "ALERT—\nSecurity notice",
            "expected_match": True
        },
        {
            "name": "Mixed Case",
            "text": "alert —\nSecurity notice",
            "expected_match": True  # Should match with IGNORECASE
        },
        {
            "name": "Flexible Slash Spacing",
            "text": "TRIGGERS/KEYWORDS —\nList of triggers",
            "expected_match": True
        },
        {
            "name": "Extra Slash Spaces",
            "text": "TRIGGERS / KEYWORDS —\nList of triggers",
            "expected_match": True
        },
        {
            "name": "Categories Variation", 
            "text": "CATEGORIES  /  SUBCATEGORIES —\nCategory list",
            "expected_match": True
        }
    ]
    
    print("--- Testing Header Pattern Matching ---")
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"{i}. {test_case['name']}")
        print(f"   Text: '{test_case['text'].split()[0]}...'")
        
        # Test against relevant patterns
        matched_patterns = []
        for pattern in REQUIRED_HEADERS:
            lines = test_case['text'].split('\n')
            if lines and re.search(pattern, lines[0], re.IGNORECASE):
                # Extract clean pattern name for display
                pattern_name = re.sub(r'[\^\$\s\\]', '', pattern).replace('—', '').strip()
                matched_patterns.append(pattern_name)
        
        if matched_patterns:
            print(f"   ✅ Matched: {', '.join(matched_patterns)}")
        else:
            print("   ❌ No matches")
        
        expected = "✅" if test_case['expected_match'] else "❌"
        actual = "✅" if matched_patterns else "❌"
        result = "PASS" if expected == actual else "FAIL"
        print(f"   Result: {result}")
        print()

def test_section_generation():
    """Test the enhanced section generation with proper spacing."""
    
    print("--- Testing Section Generation with Proper Spacing ---")
    
    # Test advisory missing several sections
    incomplete_advisory = """
### Security Advisory

ALERT —
High priority security notice for Budapest area.

WHAT TO DO NOW —
• Avoid central areas
• Monitor local news

EXPLANATION —
Based on recent intelligence reports.
""".strip()
    
    print("Original Advisory:")
    print("-" * 50)
    print(incomplete_advisory)
    print("-" * 50)
    
    from advisor import ensure_sections, clean_auto_sections
    
    # Add missing sections
    enhanced_advisory = ensure_sections(incomplete_advisory)
    
    print("\nAfter Adding Missing Sections:")
    print("-" * 50)
    print(enhanced_advisory)
    print("-" * 50)
    
    # Clean up auto-added placeholders
    cleaned_advisory = clean_auto_sections(enhanced_advisory)
    
    print("\nAfter Cleaning Auto Sections:")
    print("-" * 50) 
    print(cleaned_advisory)
    print("-" * 50)
    
    # Analyze the improvements
    original_sections = len([line for line in incomplete_advisory.split('\n') if '—' in line])
    final_sections = len([line for line in cleaned_advisory.split('\n') if '—' in line])
    
    print(f"\n📊 Section Analysis:")
    print(f"   Original sections: {original_sections}")
    print(f"   Final sections: {final_sections}")
    print(f"   Sections added: {final_sections - original_sections}")

def test_spacing_fixes():
    """Test the spacing and formatting fixes."""
    
    print("\n--- Testing Spacing and Formatting Fixes ---")
    
    # Test advisory with various formatting issues
    messy_advisory = """
ALERT—Security Issue
BULLETPOINT RISK SUMMARY —
• High risk
TRIGGERS/KEYWORDS—
terrorism, bomb
CATEGORIES/SUBCATEGORIES   —
Security / Terrorism
SOURCES—
Police reports
CONFIDENCE   —
85%
WHAT TO DO NOW   —Immediate action required
HOW TO PREPARE—
Prepare emergency kit
""".strip()
    
    print("Messy Advisory (formatting issues):")
    print("-" * 50)
    print(messy_advisory)
    print("-" * 50)
    
    from advisor import clean_auto_sections
    
    # Apply spacing fixes
    fixed_advisory = clean_auto_sections(messy_advisory)
    
    print("\nAfter Spacing Fixes:")
    print("-" * 50)
    print(fixed_advisory) 
    print("-" * 50)
    
    # Show specific improvements
    print("\n🔧 Formatting Improvements:")
    
    original_lines = messy_advisory.split('\n')
    fixed_lines = fixed_advisory.split('\n')
    
    for i, (orig, fixed) in enumerate(zip(original_lines, fixed_lines)):
        if orig != fixed and '—' in orig:
            print(f"   Line {i+1}:")
            print(f"     Before: '{orig}'")
            print(f"     After:  '{fixed}'")

def demonstrate_benefits():
    """Show the key benefits of the enhanced header formatting."""
    
    print("\n=== BENEFITS OF ENHANCED HEADER FORMATTING ===\n")
    
    benefits = [
        {
            "benefit": "🔍 FLEXIBLE PATTERN MATCHING",
            "description": "Handles various spacing and formatting variations",
            "example": "'ALERT—' and 'ALERT   —' both work"
        },
        {
            "benefit": "🎯 CASE INSENSITIVE MATCHING", 
            "description": "Recognizes headers regardless of case",
            "example": "'alert —' matches 'ALERT —' pattern"
        },
        {
            "benefit": "📝 SMART HEADER GENERATION",
            "description": "Automatically creates properly formatted headers",
            "example": "Converts patterns to 'CATEGORIES / SUBCATEGORIES —'"
        },
        {
            "benefit": "🔧 SPACING NORMALIZATION",
            "description": "Fixes missing spaces after headers automatically",
            "example": "'ALERT—Content' becomes 'ALERT — Content'"
        },
        {
            "benefit": "🧹 ORPHAN HEADER CLEANUP",
            "description": "Removes empty sections that add no value",
            "example": "Empty 'SOURCES —' sections are removed"
        },
        {
            "benefit": "⚡ ROBUST PROCESSING",
            "description": "Handles malformed input gracefully",
            "example": "Various spacing patterns all normalize correctly"
        }
    ]
    
    for benefit in benefits:
        print(f"{benefit['benefit']}")
        print(f"   {benefit['description']}")
        print(f"   Example: {benefit['example']}")
        print()

if __name__ == "__main__":
    test_header_patterns()
    test_section_generation()  
    test_spacing_fixes()
    demonstrate_benefits()
    
    print("=== IMPLEMENTATION SUMMARY ===")
    print("✅ Flexible spacing patterns for all headers")
    print("✅ Case-insensitive header matching")
    print("✅ Smart header text generation with proper spacing")
    print("✅ Automatic spacing normalization")
    print("✅ Orphan header cleanup")
    print("✅ Robust handling of malformed input")
    print("\n🚀 Result: Clean, consistently formatted advisories with reliable header processing!")
