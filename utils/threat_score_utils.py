"""
Threat Score Components Utilities
Helper functions for formatting and displaying threat scoring breakdowns
"""

from typing import Dict, Optional, List


def format_score_components(components: Optional[Dict]) -> Dict:
    """
    Format threat_score_components for API display.
    
    Args:
        components: Raw threat_score_components dict from alert
        
    Returns:
        Formatted dict with human-readable labels and values
    """
    if not components or not isinstance(components, dict):
        return {
            "available": False,
            "message": "No scoring breakdown available"
        }
    
    formatted = {
        "available": True,
        "breakdown": {}
    }
    
    # SOCMINT contribution
    if 'socmint_raw' in components:
        formatted["breakdown"]["socmint"] = {
            "raw_score": components.get('socmint_raw', 0),
            "weighted_contribution": components.get('socmint_weighted', 0),
            "weight_percent": int(components.get('socmint_weight', 0) * 100),
            "description": "Social media intelligence from profile analysis"
        }
    
    # Base score (before augmentation)
    if 'base_score' in components:
        formatted["breakdown"]["base"] = {
            "score": components.get('base_score', 0),
            "description": "Core threat assessment before SOCMINT"
        }
    
    # Final score
    if 'final_score' in components:
        formatted["final_score"] = components.get('final_score')
    
    return formatted


def calculate_score_impact(components: Optional[Dict]) -> Dict:
    """
    Calculate the impact of different scoring factors.
    
    Args:
        components: threat_score_components dict
        
    Returns:
        Dict with impact analysis
    """
    if not components or not isinstance(components, dict):
        return {"available": False}
    
    impact = {
        "available": True,
        "factors": []
    }
    
    base = components.get('base_score', 0)
    final = components.get('final_score', base)
    
    # SOCMINT impact
    socmint_weighted = components.get('socmint_weighted', 0)
    if socmint_weighted > 0:
        impact["factors"].append({
            "name": "SOCMINT",
            "impact": socmint_weighted,
            "impact_percent": round((socmint_weighted / final) * 100, 1) if final > 0 else 0,
            "change": f"+{socmint_weighted}"
        })
    
    # Base contribution
    if base > 0:
        impact["factors"].append({
            "name": "Base Assessment",
            "impact": base,
            "impact_percent": round((base / final) * 100, 1) if final > 0 else 0,
            "change": "baseline"
        })
    
    impact["total_score"] = final
    impact["enhancement_percent"] = round(((final - base) / base) * 100, 1) if base > 0 else 0
    
    return impact


def get_socmint_details(components: Optional[Dict]) -> Dict:
    """
    Extract SOCMINT-specific scoring details.
    
    Args:
        components: threat_score_components dict
        
    Returns:
        Dict with SOCMINT scoring breakdown
    """
    if not components or not isinstance(components, dict):
        return {"available": False}
    
    if 'socmint_raw' not in components:
        return {
            "available": False,
            "message": "No SOCMINT data contributed to this alert"
        }
    
    raw_score = components.get('socmint_raw', 0)
    weighted = components.get('socmint_weighted', 0)
    weight = components.get('socmint_weight', 0.3)
    
    # Estimate component breakdown (reverse engineering from total)
    # These are heuristics based on the scoring logic in threat_engine.py
    details = {
        "available": True,
        "raw_score": raw_score,
        "weighted_score": weighted,
        "weight_applied": weight,
        "estimated_factors": []
    }
    
    # Follower impact (0-15 points)
    if raw_score >= 15:
        details["estimated_factors"].append({
            "factor": "High follower count",
            "impact": "15 points",
            "description": ">100k followers"
        })
    elif raw_score >= 10:
        details["estimated_factors"].append({
            "factor": "Medium follower count",
            "impact": "10 points",
            "description": "10k-100k followers"
        })
    elif raw_score >= 5:
        details["estimated_factors"].append({
            "factor": "Low follower count",
            "impact": "5 points",
            "description": "1k-10k followers"
        })
    
    # Recency bonus (~10 points)
    if raw_score >= 10:
        details["estimated_factors"].append({
            "factor": "Recent activity",
            "impact": "~10 points",
            "description": "Post within last 7 days"
        })
    
    # IOC detection (0-20 points)
    if raw_score >= 20:
        details["estimated_factors"].append({
            "factor": "IOC mentions",
            "impact": "5-20 points",
            "description": "CVEs, IPs, domains in posts"
        })
    
    return details


def format_for_ui(components: Optional[Dict]) -> List[Dict]:
    """
    Format scoring components for UI display (e.g., progress bars, charts).
    
    Args:
        components: threat_score_components dict
        
    Returns:
        List of display-ready factor dicts
    """
    if not components or not isinstance(components, dict):
        return []
    
    ui_factors = []
    
    # Base score
    base = components.get('base_score', 0)
    if base > 0:
        ui_factors.append({
            "label": "Base Threat Assessment",
            "value": base,
            "percentage": 100,  # Baseline
            "color": "#3b82f6",  # Blue
            "icon": "shield"
        })
    
    # SOCMINT enhancement
    socmint_weighted = components.get('socmint_weighted', 0)
    if socmint_weighted > 0:
        final = components.get('final_score', base + socmint_weighted)
        ui_factors.append({
            "label": "SOCMINT Intelligence",
            "value": socmint_weighted,
            "percentage": round((socmint_weighted / final) * 100, 1) if final > 0 else 0,
            "color": "#8b5cf6",  # Purple
            "icon": "users",
            "details": f"From social media analysis (raw: {components.get('socmint_raw', 0)})"
        })
    
    return ui_factors


# Example usage:
if __name__ == "__main__":
    # Sample components from an alert
    sample_components = {
        "socmint_raw": 15.0,
        "socmint_weighted": 4.5,
        "socmint_weight": 0.3,
        "base_score": 60.0,
        "final_score": 64.5
    }
    
    print("1. Formatted Components:")
    print(format_score_components(sample_components))
    
    print("\n2. Score Impact:")
    print(calculate_score_impact(sample_components))
    
    print("\n3. SOCMINT Details:")
    print(get_socmint_details(sample_components))
    
    print("\n4. UI Format:")
    print(format_for_ui(sample_components))
