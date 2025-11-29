#!/usr/bin/env python3
"""
Threat Keywords Validation Script

This script validates the threat_keywords.json file to ensure it meets 
the required format and content standards. Run this before committing
changes to threat_keywords.json.

Usage:
    python validate_keywords.py [--path config/threat_keywords.json]
"""

import argparse
import json
import os
import sys
from typing import Dict, Set

def validate_structure(data: Dict) -> bool:
    """Validate the basic structure of keywords data."""
    errors = []
    
    # Check required fields
    if "keywords" not in data:
        errors.append("Missing required 'keywords' field")
    elif not isinstance(data["keywords"], list):
        errors.append("'keywords' field must be a list")
    
    # Validate keywords content
    if "keywords" in data:
        for i, keyword in enumerate(data["keywords"]):
            if not isinstance(keyword, str):
                errors.append(f"Keyword at index {i} must be a string")
            elif not keyword.strip():
                errors.append(f"Keyword at index {i} is empty or whitespace only")
            elif len(keyword) > 200:
                errors.append(f"Keyword at index {i} is too long ({len(keyword)} chars)")
    
    # Validate translated structure
    if "translated" in data:
        if not isinstance(data["translated"], dict):
            errors.append("'translated' field must be a dictionary")
        else:
            for category, translations in data["translated"].items():
                if not isinstance(translations, dict):
                    errors.append(f"Translation category '{category}' must be a dictionary")
                    continue
                
                for lang_code, terms in translations.items():
                    if not isinstance(terms, list):
                        errors.append(f"Translation {category}.{lang_code} must be a list")
                        continue
                    
                    for j, term in enumerate(terms):
                        if not isinstance(term, str):
                            errors.append(f"Translation term {category}.{lang_code}[{j}] must be a string")
                        elif not term.strip():
                            errors.append(f"Translation term {category}.{lang_code}[{j}] is empty")
    
    if errors:
        for error in errors:
            print(f"❌ {error}")
        return False
    
    return True

def analyze_content(data: Dict) -> Dict:
    """Analyze keyword content and provide statistics."""
    stats = {
        "total_keywords": len(data.get("keywords", [])),
        "translation_categories": len(data.get("translated", {})),
        "languages": set(),
        "duplicate_keywords": set(),
        "potential_issues": []
    }
    
    # Check for duplicates in base keywords
    keywords = data.get("keywords", [])
    seen = set()
    for keyword in keywords:
        if keyword.lower() in seen:
            stats["duplicate_keywords"].add(keyword)
        seen.add(keyword.lower())
    
    # Collect language codes
    translated = data.get("translated", {})
    for category, translations in translated.items():
        for lang_code in translations.keys():
            stats["languages"].add(lang_code)
    
    # Check for potential issues
    if stats["total_keywords"] == 0:
        stats["potential_issues"].append("No base keywords defined")
    
    if stats["total_keywords"] > 1000:
        stats["potential_issues"].append(f"Very large keyword list ({stats['total_keywords']} keywords)")
    
    if stats["duplicate_keywords"]:
        stats["potential_issues"].append(f"{len(stats['duplicate_keywords'])} duplicate keywords found")
    
    # Check for incomplete translations
    if translated:
        lang_counts = {}
        for category, translations in translated.items():
            for lang_code, terms in translations.items():
                lang_counts[lang_code] = lang_counts.get(lang_code, 0) + len(terms)
        
        # Check if any language has significantly fewer terms
        if len(lang_counts) > 1:
            max_terms = max(lang_counts.values())
            for lang, count in lang_counts.items():
                if count < max_terms * 0.7:  # Less than 70% of max
                    stats["potential_issues"].append(
                        f"Language '{lang}' may have incomplete translations ({count} vs {max_terms} terms)"
                    )
    
    return stats

def print_report(data: Dict, stats: Dict) -> None:
    """Print a detailed validation report."""
    print("\n📊 THREAT KEYWORDS VALIDATION REPORT")
    print("=" * 50)
    
    # Basic statistics
    print(f"✅ Total base keywords: {stats['total_keywords']}")
    print(f"✅ Translation categories: {stats['translation_categories']}")
    print(f"✅ Languages supported: {len(stats['languages'])}")
    if stats['languages']:
        print(f"   Languages: {', '.join(sorted(stats['languages']))}")
    
    # Duplicates
    if stats['duplicate_keywords']:
        print(f"\n⚠️  Duplicate keywords found:")
        for dup in sorted(stats['duplicate_keywords']):
            print(f"   - {dup}")
    else:
        print(f"\n✅ No duplicate keywords detected")
    
    # Potential issues
    if stats['potential_issues']:
        print(f"\n⚠️  Potential Issues:")
        for issue in stats['potential_issues']:
            print(f"   - {issue}")
    else:
        print(f"\n✅ No issues detected")
    
    # Translation coverage
    if "translated" in data:
        print(f"\n📝 Translation Coverage:")
        for category, translations in data["translated"].items():
            lang_terms = {lang: len(terms) for lang, terms in translations.items()}
            print(f"   {category}: {dict(sorted(lang_terms.items()))}")

def main():
    parser = argparse.ArgumentParser(description="Validate threat_keywords.json file")
    parser.add_argument(
        "--path", 
        default="config/threat_keywords.json",
        help="Path to threat_keywords.json file"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable strict validation (fail on warnings)"
    )
    
    args = parser.parse_args()
    
    # Check if file exists
    if not os.path.exists(args.path):
        print(f"❌ File not found: {args.path}")
        sys.exit(1)
    
    # Load and parse JSON
    try:
        with open(args.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"✅ Successfully loaded: {args.path}")
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to read file: {e}")
        sys.exit(1)
    
    # Validate structure
    print("\n🔍 Validating structure...")
    if not validate_structure(data):
        print("\n❌ Validation failed")
        sys.exit(1)
    
    print("✅ Structure validation passed")
    
    # Analyze content
    stats = analyze_content(data)
    print_report(data, stats)
    
    # Exit code based on findings
    if stats['potential_issues']:
        if args.strict:
            print("\n❌ Strict mode: failing due to warnings")
            sys.exit(1)
        else:
            print("\n⚠️  Validation completed with warnings")
            sys.exit(0)
    else:
        print("\n✅ Validation completed successfully")
        sys.exit(0)

if __name__ == "__main__":
    main()
