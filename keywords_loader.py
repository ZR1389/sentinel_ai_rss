"""
keywords_loader.py - Single source of truth for all keyword taxonomies

Centralizes keyword definitions from:
1. risk_shared.py: CATEGORY_KEYWORDS, DOMAIN_KEYWORDS  
2. config/threat_keywords.json: keywords, conditional, translated
3. threat_scorer.py: SEVERE_TERMS, MOBILITY_TERMS, INFRA_TERMS

This becomes the ONLY file to edit for keyword management.
All other modules should import from here to maintain consistency.
"""

import json
import os
from typing import Dict, List

# Load the base keyword data from threat_keywords.json
def _load_keyword_data() -> Dict:
    """Load keyword data from the JSON file with proper path resolution."""
    # Try different possible paths
    possible_paths = [
        "config/threat_keywords.json",
        "threat_keywords.json",
        os.path.join(os.path.dirname(__file__), "config/threat_keywords.json"),
        os.path.join(os.path.dirname(__file__), "threat_keywords.json")
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    
    # Fallback empty structure if file not found
    print(f"Warning: threat_keywords.json not found in any of these locations: {possible_paths}")
    return {"keywords": [], "conditional": {"broad_terms": [], "impact_terms": []}, "translated": {}}

KEYWORD_DATA = _load_keyword_data()

# =====================================================================
# CATEGORY KEYWORDS (for risk_shared.py and general categorization)
# =====================================================================

def _build_category_keywords() -> Dict[str, List[str]]:
    """Build category keywords by combining and organizing JSON data."""
    
    # Base keywords from JSON
    base_keywords = KEYWORD_DATA.get("keywords", [])
    translated = KEYWORD_DATA.get("translated", {})
    
    # Helper to get English translations
    def get_en_terms(category_key: str) -> List[str]:
        return translated.get(category_key, {}).get("en", [])
    
    return {
        "Crime": [
            "robbery", "assault", "shooting", "stabbing", "murder", "burglary", "theft", 
            "carjacking", "homicide", "looting", "kidnap", "kidnapping", "abduction", 
            "arson", "home invasion", "armed robbery", "assault on a foreigner", 
            "assault on a tourist", "mugging", "human trafficking", "sex trafficking", 
            "rape", "sexual assault", "violent crime"
        ] + get_en_terms("assassination") + get_en_terms("kidnapping") + get_en_terms("human trafficking"),
        
        "Terrorism": [
            "ied", "vbied", "suicide bomber", "terrorist", "bomb", "explosion", "martyrdom",
            "blast", "grenade", "improvised explosive", "car bomb", "truck bomb", "shelling", 
            "mortar", "drone strike", "airstrike", "air strike", "artillery", "bombing",
            "roadside bomb", "terrorist attack", "terrorism", "suicide bombing", "drone attack", 
            "road ambush", "extremist activity", "radicalization", "jihadist", "extremism",
            "armed groups", "militia attacks", "armed militants", "separatists"
        ] + get_en_terms("terrorism") + get_en_terms("jihadist") + get_en_terms("extremism"),
        
        "Civil Unrest": [
            "protest", "riot", "demonstration", "march", "sit-in", "clash", "looting", 
            "roadblock", "strike", "civil unrest", "political unrest", "uprising", 
            "insurrection", "political turmoil", "political crisis", "clashes", 
            "arson", "barricades", "tire burning", "stone throwing", "tear gas", 
            "rubber bullets", "water cannon", "live fire"
        ] + get_en_terms("protest"),
        
        "Cyber": [
            "ransomware", "phishing", "malware", "breach", "ddos", "credential", "data leak", 
            "data leakage", "zero-day", "zero day", "cve", "exploit", "backdoor", 
            "credential stuffing", "wiper", "data breach", "cyberattack", "hacktivism", 
            "cyber espionage", "identity theft", "network breach", "digital kidnapping", 
            "virtual kidnapping", "cyber kidnapping", "honey trap", "hacking attack",
            "cyber fraud", "crypto fraud", "deepfake"
        ] + get_en_terms("cyberattack") + get_en_terms("cyber espionage") + get_en_terms("digital kidnapping"),
        
        "Infrastructure": [
            "substation", "pipeline", "power outage", "grid", "transformer", "telecom", 
            "fiber", "water plant", "facility", "sabotage", "blackout", "subsea cable", 
            "dam", "bridge", "transformer fire", "substation fire", "refinery", "refinery fire",
            "refinery explosion", "gas leak", "ammonia leak", "chlorine leak", "chemical spill", 
            "oil spill", "hazmat", "scada", "ics", "plc", "ot", "industrial control", "hmi"
        ] + KEYWORD_DATA.get("conditional", {}).get("broad_terms", []),
        
        "Environmental": [
            "earthquake", "flood", "hurricane", "storm", "wildfire", "heatwave", "landslide", 
            "mudslide", "tornado", "cyclone", "natural disaster", "tsunami", "flash flood", 
            "wild fire", "rockslide", "avalanche", "volcanic eruption", "ash plume", "lahar", 
            "heat wave", "blizzard", "snowstorm", "cold snap", "dam burst", "levee breach"
        ] + get_en_terms("natural disaster"),
        
        "Epidemic": [
            "epidemic", "pandemic", "outbreak", "cholera", "dengue", "covid", "ebola", 
            "avian flu", "viral outbreak", "disease spread", "contamination", "quarantine",
            "public health emergency", "infectious disease", "biological threat", "health alert"
        ] + get_en_terms("pandemic") + get_en_terms("epidemic"),
        
        "Military": [
            "military coup", "military raid", "coup d'etat", "regime change", "military takeover",
            "state of emergency", "martial law", "curfew", "roadblock", "police raid"
        ] + get_en_terms("military coup") + get_en_terms("state of emergency"),
        
        "Other": []
    }

CATEGORY_KEYWORDS = _build_category_keywords()

# =====================================================================
# SUBCATEGORY MAPPING (for risk_shared.py)
# =====================================================================

SUBCATEGORY_MAP: Dict[str, Dict[str, str]] = {
    "Crime": {
        "robbery": "Armed Robbery", "assault": "Aggravated Assault", "shooting": "Targeted Shooting",
        "stabbing": "Knife Attack", "burglary": "Burglary", "carjacking": "Carjacking", 
        "looting": "Looting", "kidnap": "Kidnap", "kidnapping": "Kidnap", "arson": "Arson",
        "human trafficking": "Human Trafficking", "sex trafficking": "Human Trafficking"
    },
    "Terrorism": {
        "ied": "IED Attack", "vbied": "VBIED", "suicide bomber": "Suicide Attack", 
        "bomb": "Bombing", "explosion": "Bombing", "grenade": "Grenade Attack", 
        "drone strike": "Drone Strike", "airstrike": "Airstrike", "air strike": "Airstrike",
        "terrorist attack": "Terrorism", "suicide bombing": "Suicide Attack"
    },
    "Civil Unrest": {
        "protest": "Protest", "riot": "Riot", "looting": "Looting", "strike": "Strike/Industrial Action",
        "roadblock": "Road Blockade", "clash": "Police–Protester Clash", "uprising": "Uprising"
    },
    "Cyber": {
        "ransomware": "Ransomware", "phishing": "Phishing", "breach": "Data Breach", "ddos": "DDoS",
        "credential": "Account Takeover", "zero-day": "Zero-Day Exploit", "zero day": "Zero-Day Exploit",
        "cve": "Vulnerability Exploitation", "credential stuffing": "Credential Stuffing", 
        "wiper": "Wiper Malware", "data leak": "Data Leak", "data leakage": "Data Leak",
        "cyberattack": "Cyber Attack", "cyber espionage": "Cyber Espionage"
    },
    "Infrastructure": {
        "pipeline": "Pipeline Incident", "substation": "Substation Sabotage", "grid": "Grid Disruption",
        "power outage": "Power Outage", "telecom": "Telecom Outage", "water plant": "Water Utility Incident",
        "facility": "Facility Incident", "blackout": "Power Outage", "subsea cable": "Subsea Cable Disruption",
        "dam": "Dam Incident", "bridge": "Bridge Closure/Incident", "transformer": "Transformer Incident"
    },
    "Environmental": {
        "flood": "Flooding", "hurricane": "Hurricane/Typhoon", "earthquake": "Earthquake",
        "wildfire": "Wildfire", "storm": "Severe Storm", "landslide": "Landslide", 
        "heatwave": "Heatwave", "tornado": "Tornado"
    },
    "Epidemic": {
        "cholera": "Cholera", "dengue": "Dengue", "covid": "COVID-19", "ebola": "Ebola", 
        "avian flu": "Avian Influenza", "outbreak": "Disease Outbreak", "pandemic": "Pandemic"
    },
    "Military": {
        "military coup": "Military Coup", "coup d'etat": "Coup d'État", "martial law": "Martial Law",
        "state of emergency": "State of Emergency", "curfew": "Curfew"
    }
}

# =====================================================================
# DOMAIN KEYWORDS (for risk_shared.py domain detection)
# =====================================================================

DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "travel_mobility": [
        "travel", "route", "road", "highway", "checkpoint", "curfew", "airport", "border", 
        "port", "rail", "metro", "detour", "closure", "traffic", "mobility", "bridge", 
        "service suspended", "border closure", "flight cancellation", "flight cancellations", 
        "airport closure", "runway closure", "airspace closed", "no-fly zone", "ground stop", 
        "NOTAM", "air traffic control", "ATC outage", "ferry suspension", "port closed", 
        "road closure", "highway closed", "train derailment", "train collision"
    ],
    
    "cyber_it": [
        "cyber", "hacker", "phishing", "ransomware", "malware", "data breach", "ddos", 
        "credential", "mfa", "passkey", "vpn", "exploit", "zero-day", "zero day", "cve", 
        "edr", "credential stuffing", "wiper", "cyberattack", "hacktivism", "cyber espionage", 
        "identity theft", "network breach", "SCADA", "ICS", "PLC", "GPS jamming", "GNSS spoofing",
        "internet shutdown", "telecom outage", "nationwide outage"
    ],
    
    "digital_privacy_surveillance": [
        "surveillance", "counter-surveillance", "device check", "imsi", "stingray", "tracking", 
        "tail", "biometric", "unlock", "spyware", "pegasus", "finfisher", "watchlist"
    ],
    
    "physical_safety": [
        "kidnap", "abduction", "theft", "assault", "shooting", "stabbing", "robbery", 
        "looting", "attack", "murder", "grenade", "arson", "assassination", "homicide", 
        "killing", "slaughter", "massacre", "mass shooting", "active shooter", "knife attack", 
        "machete attack", "lynching", "hijacking", "hostage situation", "carjacking", 
        "home invasion", "mugging", "violent crime"
    ],
    
    "civil_unrest": [
        "protest", "riot", "demonstration", "clash", "strike", "roadblock", "sit-in", "march", 
        "uprising", "insurrection", "clashes", "looting", "arson", "barricades", "tire burning", 
        "stone throwing", "tear gas", "rubber bullets", "water cannon", "live fire"
    ],
    
    "kfr_extortion": [
        "kidnap", "kidnapping", "kfr", "ransom", "extortion", "hostage", "express kidnapping", 
        "kidnap-for-ransom", "blackmail", "false imprisonment"
    ],
    
    "infrastructure_utilities": [
        "infrastructure", "power", "grid", "substation", "pipeline", "telecom", "fiber", 
        "facility", "sabotage", "water", "blackout", "subsea cable", "transformer", "dam", 
        "power blackout", "power outage", "refinery", "refinery fire", "refinery explosion", 
        "gas leak", "chemical spill", "oil spill", "hazmat"
    ],
    
    "environmental_hazards": [
        "earthquake", "flood", "hurricane", "storm", "wildfire", "heatwave", "landslide", 
        "mudslide", "tornado", "cyclone", "natural disaster", "tsunami", "flash flood", 
        "wild fire", "volcanic eruption", "avalanche", "blizzard", "dam burst", "levee breach"
    ],
    
    "public_health_epidemic": [
        "epidemic", "pandemic", "outbreak", "cholera", "dengue", "covid", "ebola", "avian flu", 
        "public health emergency", "disease spread", "contamination", "quarantine", 
        "infectious disease", "biological threat"
    ],
    
    "ot_ics": [
        "scada", "ics", "plc", "ot", "industrial control", "hmi"
    ],
    
    "info_ops_disinfo": [
        "misinformation", "disinformation", "propaganda", "info ops", "psyop", "deepfake"
    ],
    
    "legal_regulatory": [
        "visa", "immigration", "border control", "curfew", "checkpoint order", "permit", 
        "license", "ban", "restriction", "travel ban", "embassy alert", "travel advisory", 
        "security alert", "evacuation"
    ],
    
    "business_continuity_supply": [
        "supply chain", "logistics", "port congestion", "warehouse", "shortage", "inventory"
    ],
    
    "insider_threat": [
        "insider", "employee", "privileged access", "badge", "tailgating"
    ],
    
    "residential_premises": [
        "residential", "home invasion", "burglary", "apartment", "compound"
    ],
    
    "emergency_medical": [
        "casualty", "injured", "fatalities", "triage", "medical", "ambulance", "killed", 
        "dead", "deaths", "fatality", "wounded", "hurt", "hospitalized", "critical condition"
    ],
    
    "counter_surveillance": [
        "surveillance", "tail", "followed", "sdr", "sd r", "surveillance detection"
    ],
    
    "terrorism": [
        "ied", "vbied", "suicide bomber", "terrorist", "bomb", "explosion", "drone strike", 
        "airstrike", "air strike", "grenade", "blast", "mortar", "artillery", "terrorist attack", 
        "terrorism", "suicide bombing", "extremist activity", "jihadist", "armed groups", 
        "militia attacks", "separatists"
    ],
    
    "military_security": [
        "military coup", "coup d'etat", "military takeover", "military raid", "state of emergency", 
        "martial law", "police raid", "heightened security", "elevated threat level"
    ]
}

# =====================================================================
# THREAT SCORER KEYWORDS (for threat_scorer.py scoring)
# =====================================================================

# Severe terms for high-impact scoring
SEVERE_TERMS = KEYWORD_DATA.get("keywords", []) + [
    # Additional severe terms not in main keywords
    "i e d", "v b i e d",  # spaced variants
    "multiple explosions", "fatal", "killed", "evacuate", "emergency"
]

# Mobility/travel impact terms  
MOBILITY_TERMS = [
    "airport", "border", "highway", "rail", "metro", "bridge", "port", "road closure", 
    "detour", "traffic suspended", "service suspended", "runway", "airspace", "notam", 
    "ground stop", "flight cancellation", "airport closure", "ferry suspension"
]

# Infrastructure impact terms
INFRA_TERMS = [
    "substation", "grid", "pipeline", "telecom", "fiber", "power outage", "blackout", 
    "water plant", "dam", "subsea cable", "transformer", "refinery", "substation fire", 
    "transformer fire", "gas leak", "chemical spill", "oil spill"
]

# =====================================================================
# CONDITIONAL AND TRANSLATED KEYWORDS (from JSON)
# =====================================================================

# Conditional keywords for context-based matching
CONDITIONAL_KEYWORDS = KEYWORD_DATA.get("conditional", {})
BROAD_TERMS = CONDITIONAL_KEYWORDS.get("broad_terms", [])
IMPACT_TERMS = CONDITIONAL_KEYWORDS.get("impact_terms", [])

# Translated keywords for multi-language support
TRANSLATED_KEYWORDS = KEYWORD_DATA.get("translated", {})

# =====================================================================
# UTILITY FUNCTIONS
# =====================================================================

def get_all_keywords() -> List[str]:
    """Get all unique keywords from all sources."""
    all_keywords = set()
    
    # Add category keywords
    for keywords in CATEGORY_KEYWORDS.values():
        all_keywords.update(keywords)
    
    # Add domain keywords  
    for keywords in DOMAIN_KEYWORDS.values():
        all_keywords.update(keywords)
    
    # Add scorer keywords
    all_keywords.update(SEVERE_TERMS)
    all_keywords.update(MOBILITY_TERMS) 
    all_keywords.update(INFRA_TERMS)
    
    # Add conditional keywords
    all_keywords.update(BROAD_TERMS)
    all_keywords.update(IMPACT_TERMS)
    
    return sorted(list(all_keywords))

def get_keywords_by_category(category: str) -> List[str]:
    """Get keywords for a specific category."""
    return CATEGORY_KEYWORDS.get(category, [])

def get_keywords_by_domain(domain: str) -> List[str]:
    """Get keywords for a specific domain."""
    return DOMAIN_KEYWORDS.get(domain, [])

def get_translated_keywords(term: str, language: str = "en") -> List[str]:
    """Get translated keywords for a term in a specific language."""
    return TRANSLATED_KEYWORDS.get(term, {}).get(language, [])

def get_categories_for_keyword(keyword: str) -> List[str]:
    """Find which categories contain a specific keyword."""
    categories = []
    keyword_lower = keyword.lower()
    
    for category, keywords in CATEGORY_KEYWORDS.items():
        if keyword_lower in [k.lower() for k in keywords]:
            categories.append(category)
    
    return categories

def get_domains_for_keyword(keyword: str) -> List[str]:
    """Find which domains contain a specific keyword."""
    domains = []
    keyword_lower = keyword.lower()
    
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if keyword_lower in [k.lower() for k in keywords]:
            domains.append(domain)
    
    return domains

# =====================================================================
# EXPORT FOR LEGACY COMPATIBILITY
# =====================================================================

# For modules that import these directly
__all__ = [
    'CATEGORY_KEYWORDS', 'SUBCATEGORY_MAP', 'DOMAIN_KEYWORDS',
    'SEVERE_TERMS', 'MOBILITY_TERMS', 'INFRA_TERMS', 
    'CONDITIONAL_KEYWORDS', 'BROAD_TERMS', 'IMPACT_TERMS',
    'TRANSLATED_KEYWORDS', 'KEYWORD_DATA',
    'get_all_keywords', 'get_keywords_by_category', 'get_keywords_by_domain',
    'get_translated_keywords', 'get_categories_for_keyword', 'get_domains_for_keyword'
]
