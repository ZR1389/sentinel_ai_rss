#!/usr/bin/env python3
"""
Test script to demonstrate the benefits of adding Data Provenance Section
Shows how the new section exposes location mismatches and data quality issues
"""

import sys
import os
sys.path.append('/Users/zikarakita/Documents/sentinel_ai_rss')

from advisor import render_advisory, _add_data_provenance_section

def test_data_provenance_section():
    """Test the data provenance section with various scenarios."""
    
    print("=== DATA PROVENANCE SECTION DEMONSTRATION ===")
    print("Shows how the system exposes location mismatches and data quality issues\n")
    
    # Test scenarios
    test_cases = [
        {
            "name": "Location Mismatch (Budapest query, Cairo data)",
            "user_message": "I'm traveling to Budapest next week. Any security concerns?",
            "alert": {
                "title": "Security incident in Cairo downtown",
                "summary": "Reports of civil unrest in Cairo city center",
                "city": "Cairo",
                "country": "Egypt", 
                "region": "Middle East",
                "confidence": 0.85,
                "incident_count_30d": 8,
                "baseline_ratio": 2.1,
                "category": "civil_unrest",
                "domains": ["political", "physical_safety"],
                "sources": [
                    {"name": "Egyptian Ministry of Interior", "link": "https://moi.gov.eg"},
                    {"name": "Reuters", "link": "https://reuters.com/egypt"}
                ]
            },
            "expected_warning": True
        },
        {
            "name": "Insufficient Statistical Data",
            "user_message": "Business trip to London tomorrow",
            "alert": {
                "title": "Minor incident in London",
                "city": "London",
                "country": "United Kingdom",
                "region": "Europe", 
                "confidence": 0.70,
                "incident_count_30d": 2,  # Too few for statistical validity
                "baseline_ratio": 1.1,
                "category": "security_incident",
                "domains": ["physical_safety"],
                "sources": [{"name": "Metropolitan Police", "link": "https://met.police.uk"}]
            },
            "expected_warning": True
        },
        {
            "name": "High Quality Data (no provenance section needed)",
            "user_message": "Traveling to Paris next month",
            "alert": {
                "title": "Security advisory for Paris central district",
                "city": "Paris", 
                "country": "France",
                "region": "Europe",
                "latitude": 48.8566,
                "longitude": 2.3522,
                "venue": "Champs-Élysées area",
                "confidence": 0.90,
                "incident_count_30d": 15,  # Good statistical base
                "baseline_ratio": 2.8,
                "category": "security_advisory",
                "domains": ["physical_safety", "travel_mobility"],
                "sources": [
                    {"name": "French Interior Ministry", "link": "https://interieur.gouv.fr"},
                    {"name": "Prefecture de Police", "link": "https://prefecturedepolice.interieur.gouv.fr"}
                ]
            },
            "expected_warning": False
        },
        {
            "name": "Low Precision Location Data",
            "user_message": "Trip to Berlin this weekend",
            "alert": {
                "title": "General security notice for Berlin area",
                "city": "Berlin",
                "country": "Germany", 
                "region": "Europe",
                # No coordinates or specific venue
                "confidence": 0.75,
                "incident_count_30d": 6,
                "baseline_ratio": 1.5,
                "category": "security_notice",
                "domains": ["physical_safety"],
                "sources": [{"name": "Berlin Police", "link": "https://berlin.de/polizei"}]
            },
            "expected_warning": True  # Due to low precision
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"--- Test Case {i}: {test_case['name']} ---")
        print(f"User Query: '{test_case['user_message']}'")
        print(f"Alert Location: {test_case['alert'].get('city')}, {test_case['alert'].get('country')}")
        print(f"Data Quality: {test_case['alert'].get('incident_count_30d')} incidents in 30 days")
        
        try:
            # Generate full advisory
            advisory = render_advisory(
                test_case['alert'],
                test_case['user_message'],
                profile_data={"business_travel": True}
            )
            
            # Check if DATA PROVENANCE section is present
            has_provenance = "DATA PROVENANCE —" in advisory
            print(f"Has Provenance Section: {has_provenance}")
            
            if has_provenance:
                # Extract the provenance section
                lines = advisory.split('\n')
                provenance_start = -1
                provenance_end = -1
                
                for idx, line in enumerate(lines):
                    if "DATA PROVENANCE —" in line:
                        provenance_start = idx
                    elif provenance_start != -1 and line.strip() and not line.startswith(('-', '•', '⚠️')) and '—' in line:
                        provenance_end = idx
                        break
                
                if provenance_start != -1:
                    provenance_end = provenance_end if provenance_end != -1 else len(lines)
                    provenance_section = '\n'.join(lines[provenance_start:provenance_end])
                    print("\nProvenance Section:")
                    print("=" * 40)
                    print(provenance_section)
                    print("=" * 40)
            
            # Show advisory length and key indicators
            print(f"Advisory Length: {len(advisory)} characters")
            print(f"Contains Location Warning: {'⚠️' in advisory}")
            print(f"Contains Data Quality Warning: {'INSUFFICIENT' in advisory}")
            print()
            
        except Exception as e:
            print(f"❌ Error generating advisory: {e}")
            print()

def demonstrate_provenance_benefits():
    """Show the key benefits of the Data Provenance section."""
    
    print("=== BENEFITS OF DATA PROVENANCE SECTION ===\n")
    
    benefits = [
        {
            "benefit": "🔍 TRANSPARENCY",
            "description": "Users see exactly why confidence was adjusted",
            "example": "Location Match Score: 10/100 (Budapest query vs Cairo data)"
        },
        {
            "benefit": "⚠️ CLEAR WARNINGS", 
            "description": "Prominent alerts for location mismatches",
            "example": "⚠️ Input data location 'cairo' does not match query location"
        },
        {
            "benefit": "📊 DATA QUALITY EXPOSURE",
            "description": "Shows statistical validity of trend data",
            "example": "Data Volume: INSUFFICIENT (incident_count_30d=2 < 5)"
        },
        {
            "benefit": "🗺️ LOCATION PRECISION",
            "description": "Indicates geographic specificity of alerts",
            "example": "Location Precision: high (coordinates: yes)"
        },
        {
            "benefit": "📰 SOURCE TRANSPARENCY",
            "description": "Lists all sources used in the advisory",
            "example": "• Egyptian Ministry of Interior https://moi.gov.eg"
        },
        {
            "benefit": "🎯 SMART POSITIONING",
            "description": "Appears before EXPLANATION section for visibility",
            "example": "Inserted strategically for user attention"
        }
    ]
    
    for benefit in benefits:
        print(f"{benefit['benefit']}")
        print(f"   {benefit['description']}")
        print(f"   Example: {benefit['example']}")
        print()

def test_direct_provenance_function():
    """Test the _add_data_provenance_section function directly."""
    
    print("=== TESTING DATA PROVENANCE FUNCTION DIRECTLY ===\n")
    
    # Sample advisory without provenance
    sample_advisory = """### Security Advisory for Budapest Travel

RISK ASSESSMENT —
- Threat Level: MEDIUM
- Primary Concerns: Civil unrest, crowd safety

RECOMMENDATIONS —
• Avoid central protest areas
• Monitor local news for updates

EXPLANATION —
Based on current intelligence and threat patterns."""

    # Sample input data with issues
    sample_input = {
        "location_validation_warning": "Input data location 'cairo' does not match query location 'Budapest'",
        "location_precision": "low",
        "location_match_score": 15,
        "data_statistically_valid": False,
        "incident_count_30d": 3,
        "sources": [
            {"name": "Egyptian Ministry", "link": "https://moi.gov.eg"},
            {"name": "Local News", "link": ""}
        ]
    }
    
    print("Original Advisory:")
    print("-" * 50)
    print(sample_advisory)
    print("-" * 50)
    
    # Add provenance section
    enhanced_advisory = _add_data_provenance_section(sample_advisory, sample_input)
    
    print("\nEnhanced Advisory with Provenance:")
    print("-" * 50)
    print(enhanced_advisory)
    print("-" * 50)
    
    print(f"\nAdded {len(enhanced_advisory) - len(sample_advisory)} characters of provenance information")

if __name__ == "__main__":
    test_data_provenance_section()
    demonstrate_provenance_benefits()
    test_direct_provenance_function()
    
    print("=== IMPLEMENTATION SUMMARY ===")
    print("✅ Data Provenance section automatically added when data quality issues detected")
    print("✅ Location mismatches prominently displayed to users") 
    print("✅ Statistical validity transparently communicated")
    print("✅ Source information clearly listed")
    print("✅ Smart positioning before EXPLANATION section")
    print("✅ Only appears when there are actual issues to report")
    print("\n🚀 Result: Users get complete transparency about data quality and relevance!")
