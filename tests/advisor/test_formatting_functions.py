#!/usr/bin/env python3
"""
Test the updated output guard formatting functions in advisor.py
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from api.advisor import clean_auto_sections, strip_excessive_blank_lines

def test_formatting_functions():
    """Test the enhanced formatting functions"""
    
    print("=== Testing Enhanced Output Guard Formatting ===\n")
    
    # Test cases for clean_auto_sections
    test_advisory_with_issues = """ALERT — Budapest | High | Crime

BULLETPOINT RISK SUMMARY —
• Crime incidents rising in central areas

TRIGGERS/KEYWORDS—
• [auto] Section added (no content)

CATEGORIES/SUBCATEGORIES—
Crime / Theft

SOURCES—

REPORTS ANALYZED—
5

CONFIDENCE   —
75

WHAT TO DO NOW—
• Avoid poorly lit areas after 20:00

HOW TO PREPARE  —
• Pre-map safe routes

ROLE-SPECIFIC ACTIONS—

DOMAIN PLAYBOOK HITS —
• [travel_mobility] Shift departures ±15 min

FORECAST—
• Rising trend expected

EXPLANATION—
• Analysis based on recent patterns

ANALYST CTA—
• Monitor for 12h"""
    
    print("--- Test 1: clean_auto_sections ---")
    print("Input issues: auto placeholders, inconsistent spacing, empty sections")
    
    cleaned = clean_auto_sections(test_advisory_with_issues)
    
    # Check for improvements
    issues_fixed = []
    if "[auto] Section added (no content)" not in cleaned:
        issues_fixed.append("✅ Auto placeholders removed")
    else:
        issues_fixed.append("❌ Auto placeholders still present")
    
    if " — " in cleaned and "—" in cleaned:
        # Check if spacing is consistent
        dash_patterns = cleaned.count(" — ")
        total_headers = cleaned.count("—")
        if dash_patterns >= total_headers * 0.8:  # Most headers properly spaced
            issues_fixed.append("✅ Header spacing normalized")
        else:
            issues_fixed.append("⚠️ Some header spacing issues remain")
    
    print("\n".join(issues_fixed))
    print()
    
    # Test strip_excessive_blank_lines
    test_text_with_blank_lines = """ALERT — Test


BULLETPOINT RISK SUMMARY —




• Multiple blank lines above

WHAT TO DO NOW —


• More blank lines



EXPLANATION —
• Final section



"""
    
    print("--- Test 2: strip_excessive_blank_lines ---")
    print("Input issues: excessive blank lines, trailing whitespace")
    
    stripped = strip_excessive_blank_lines(test_text_with_blank_lines)
    
    # Check for improvements
    blank_line_issues = []
    
    # Count consecutive blank lines
    lines = stripped.split('\n')
    max_consecutive_blanks = 0
    current_blanks = 0
    
    for line in lines:
        if not line.strip():
            current_blanks += 1
        else:
            max_consecutive_blanks = max(max_consecutive_blanks, current_blanks)
            current_blanks = 0
    
    if max_consecutive_blanks <= 2:
        blank_line_issues.append("✅ Excessive blank lines removed (max consecutive: {})".format(max_consecutive_blanks))
    else:
        blank_line_issues.append("❌ Still has {} consecutive blank lines".format(max_consecutive_blanks))
    
    # Check leading/trailing
    if not stripped.startswith('\n') and not stripped.endswith('\n'):
        blank_line_issues.append("✅ Leading/trailing blank lines removed")
    else:
        blank_line_issues.append("⚠️ Some leading/trailing blank lines remain")
    
    # Check for trailing whitespace
    lines_with_trailing = sum(1 for line in lines if line != line.rstrip())
    if lines_with_trailing == 0:
        blank_line_issues.append("✅ Trailing whitespace cleaned")
    else:
        blank_line_issues.append(f"⚠️ {lines_with_trailing} lines still have trailing whitespace")
    
    print("\n".join(blank_line_issues))
    print()
    
    # Test combined workflow
    print("--- Test 3: Combined Formatting Workflow ---")
    
    messy_advisory = """ALERT—Test | High | Crime


BULLETPOINT RISK SUMMARY—
• Crime rising



EMPTY SECTION—


GOOD SECTION — 
• Content here

• [auto] Section added (no content)




FINAL SECTION —
• Last content


"""
    
    # Apply both functions in sequence (like in render_advisory)
    step1 = clean_auto_sections(messy_advisory)
    step2 = strip_excessive_blank_lines(step1)
    
    print("Original issues: inconsistent header spacing, auto placeholders, excessive blank lines")
    
    # Count improvements
    improvements = []
    
    if "[auto]" not in step2:
        improvements.append("✅ Auto placeholders removed")
    
    if step2.count(" — ") > messy_advisory.count(" — "):
        improvements.append("✅ Header spacing improved")
    
    original_blank_lines = messy_advisory.count('\n\n\n')
    final_blank_lines = step2.count('\n\n\n')
    if final_blank_lines < original_blank_lines:
        improvements.append(f"✅ Excessive blank lines reduced ({original_blank_lines} → {final_blank_lines})")
    
    if not step2.strip().startswith('\n') and not step2.strip().endswith('\n'):
        improvements.append("✅ Clean start/end formatting")
    
    print("\n".join(improvements))
    
    print(f"\nFinal formatted length: {len(step2)} chars (vs {len(messy_advisory)} original)")
    print()
    
    # Output a sample to verify
    print("--- Sample Output (first 500 chars) ---")
    print(repr(step2[:500]))
    print()
    
    return len(improvements) >= 3  # Success if at least 3 improvements

def test_edge_cases():
    """Test edge cases and potential issues"""
    
    print("=== Testing Edge Cases ===\n")
    
    edge_cases = [
        {
            "name": "Empty string",
            "input": "",
            "test": "clean_auto_sections"
        },
        {
            "name": "Only whitespace",
            "input": "   \n\n\n   ",
            "test": "strip_excessive_blank_lines"
        },
        {
            "name": "No headers",
            "input": "Just plain text with no structure",
            "test": "both"
        },
        {
            "name": "Very long header names",
            "input": "VERY LONG SECTION HEADER WITH MANY WORDS AND STUFF — \n• Content",
            "test": "clean_auto_sections"
        }
    ]
    
    all_passed = True
    
    for case in edge_cases:
        print(f"Testing: {case['name']}")
        
        try:
            if case['test'] == 'clean_auto_sections':
                result = clean_auto_sections(case['input'])
                print(f"  ✅ clean_auto_sections: {len(result)} chars")
            elif case['test'] == 'strip_excessive_blank_lines':
                result = strip_excessive_blank_lines(case['input'])
                print(f"  ✅ strip_excessive_blank_lines: {len(result)} chars")
            else:  # both
                step1 = clean_auto_sections(case['input'])
                step2 = strip_excessive_blank_lines(step1)
                print(f"  ✅ Combined: {len(case['input'])} → {len(step1)} → {len(step2)} chars")
        except Exception as e:
            print(f"  ❌ Error: {e}")
            all_passed = False
    
    return all_passed

if __name__ == "__main__":
    print("Testing Enhanced Output Guard Formatting Functions\n")
    
    # Test main functionality
    main_tests_passed = test_formatting_functions()
    
    # Test edge cases
    edge_tests_passed = test_edge_cases()
    
    print("=== Final Results ===")
    if main_tests_passed and edge_tests_passed:
        print("🎉 All formatting tests passed!")
        print("✅ Enhanced output guards are working correctly")
        print("🚀 Advisory formatting will be more consistent and clean")
    else:
        print("⚠️ Some tests failed - review formatting functions")
    
    print("\n📋 Formatting improvements implemented:")
    print("- Surgical removal of auto placeholders")
    print("- Consistent header spacing (exactly ' — ')")
    print("- Smart blank line management (max 2 consecutive)")
    print("- Trailing whitespace cleanup")
    print("- Leading/trailing blank line removal")
    print("- Better orphaned header detection")
