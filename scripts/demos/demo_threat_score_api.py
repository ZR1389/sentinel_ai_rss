#!/usr/bin/env python3
"""
Demo: Threat Score Components API
Shows how to access and display threat scoring breakdowns
"""

from threat_score_utils import (
    format_score_components,
    calculate_score_impact,
    get_socmint_details,
    format_for_ui
)


def demo_api_response():
    """Simulate API response with threat_score_components."""
    print("=" * 70)
    print("THREAT SCORE COMPONENTS API DEMO")
    print("=" * 70)
    
    # Simulate alert data from API
    alert_data = {
        "uuid": "abc-123",
        "title": "Ransomware actor posts new leak",
        "score": 64.5,
        "threat_level": "HIGH",
        "confidence": 0.85,
        "threat_score_components": {
            "socmint_raw": 15.0,
            "socmint_weighted": 4.5,
            "socmint_weight": 0.3,
            "base_score": 60.0,
            "final_score": 64.5
        }
    }
    
    print("\n1. Raw API Response:")
    print(f"   Alert: {alert_data['title']}")
    print(f"   Final Score: {alert_data['score']}")
    print(f"   Threat Level: {alert_data['threat_level']}")
    print(f"   Components: {alert_data['threat_score_components']}")
    
    # Format for display
    print("\n2. Formatted Breakdown:")
    formatted = format_score_components(alert_data['threat_score_components'])
    for key, value in formatted.items():
        if key == 'breakdown':
            print(f"   {key}:")
            for factor, details in value.items():
                print(f"      {factor}: {details}")
        else:
            print(f"   {key}: {value}")
    
    # Calculate impact
    print("\n3. Score Impact Analysis:")
    impact = calculate_score_impact(alert_data['threat_score_components'])
    print(f"   Total Score: {impact['total_score']}")
    print(f"   Enhancement: +{impact['enhancement_percent']}%")
    print(f"   Factors:")
    for factor in impact['factors']:
        print(f"      - {factor['name']}: {factor['impact']} ({factor['impact_percent']}% of total)")
    
    # SOCMINT details
    print("\n4. SOCMINT Contribution Details:")
    socmint = get_socmint_details(alert_data['threat_score_components'])
    if socmint['available']:
        print(f"   Raw Score: {socmint['raw_score']}")
        print(f"   Weighted Score: {socmint['weighted_score']}")
        print(f"   Weight Applied: {socmint['weight_applied']*100}%")
        print(f"   Estimated Factors:")
        for factor in socmint['estimated_factors']:
            print(f"      - {factor['factor']}: {factor['impact']} ({factor['description']})")
    
    # UI format
    print("\n5. UI Display Format (for charts/progress bars):")
    ui_factors = format_for_ui(alert_data['threat_score_components'])
    for factor in ui_factors:
        bar = '█' * int(factor['percentage'] / 5)  # Simple bar chart
        print(f"   {factor['label']:30} [{bar:<20}] {factor['value']:.1f} ({factor['percentage']:.1f}%)")
        if 'details' in factor:
            print(f"      └─ {factor['details']}")


def demo_api_endpoints():
    """Show example API endpoint usage."""
    print("\n" + "=" * 70)
    print("API ENDPOINT EXAMPLES")
    print("=" * 70)
    
    print("\n1. Get all alerts with scoring components:")
    print("   GET /alerts?limit=50")
    print("   Response: { alerts: [{ uuid, score, threat_score_components, ... }] }")
    
    print("\n2. Get latest alerts with components:")
    print("   GET /alerts/latest?limit=20&region=Europe")
    print("   Response: { ok: true, items: [{ uuid, score, threat_score_components, ... }] }")
    
    print("\n3. Get detailed scoring breakdown for specific alert:")
    print("   GET /alerts/abc-123/scoring")
    print("""   Response: {
     ok: true,
     alert: {
       uuid: 'abc-123',
       title: 'Ransomware actor posts new leak',
       score: 64.5,
       threat_level: 'HIGH',
       threat_score_components: {
         socmint_raw: 15.0,
         socmint_weighted: 4.5,
         socmint_weight: 0.3,
         base_score: 60.0,
         final_score: 64.5
       }
     }
   }""")
    
    print("\n4. Frontend Integration Example (JavaScript):")
    print("""
   // Fetch alert with scoring details
   const response = await fetch('/alerts/abc-123/scoring', {
     headers: { 'Authorization': `Bearer ${token}` }
   });
   const { alert } = await response.json();
   
   // Display score breakdown
   if (alert.threat_score_components) {
     const socmint = alert.threat_score_components.socmint_weighted || 0;
     const base = alert.threat_score_components.base_score || 0;
     
     console.log(`Base Score: ${base}`);
     console.log(`SOCMINT Boost: +${socmint} (${(socmint/alert.score*100).toFixed(1)}%)`);
     console.log(`Final Score: ${alert.score}`);
   }
   """)


def demo_without_socmint():
    """Show alert without SOCMINT contribution."""
    print("\n" + "=" * 70)
    print("ALERT WITHOUT SOCMINT DATA")
    print("=" * 70)
    
    alert_no_socmint = {
        "uuid": "xyz-789",
        "title": "Infrastructure vulnerability detected",
        "score": 55.0,
        "threat_score_components": {
            "base_score": 55.0,
            "final_score": 55.0
        }
    }
    
    print(f"\n   Alert: {alert_no_socmint['title']}")
    print(f"   Score: {alert_no_socmint['score']}")
    
    socmint = get_socmint_details(alert_no_socmint['threat_score_components'])
    if not socmint['available']:
        print(f"   SOCMINT: {socmint['message']}")
        print("   → This alert was scored without social media intelligence")


if __name__ == '__main__':
    demo_api_response()
    demo_api_endpoints()
    demo_without_socmint()
    
    print("\n" + "=" * 70)
    print("✅ Demo complete! Check SOCMINT_API_EXPOSURE.md for full docs.")
    print("=" * 70)
