# advisor.py — Sentinel Advisor (Final v2025-08-12 + patches v2025-08-25)
# - Reads enriched alerts (schema aligned)
# - Enforces PHYSICAL+DIGITAL, NOW+PREP, role-specific sections
# - Programmatic domain playbook hits, richer alternatives
# - Mandatory "Because X trend, do Y" line
# - Output guard ensures all sections exist and at least one playbook/alternatives appear
# - NEW (2025-08-25): multi-alert merge, predictive tone from future_risk_probability,
#   source reliability & info-ops flags, soft sports-context guard, proactive monitoring meta.
# - UPDATED (2025-11-02): Sequential LLM routing (Primary: DeepSeek → Fallback: OpenAI → Tertiary: Grok)
#   with model_used logging; optional env override ADVISOR_PROVIDER_* without changing defaults.

import os
import json
import logging
import re
import decimal
from typing import Dict, Any, List, Optional, Tuple

from dotenv import load_dotenv

from llm_router import route_llm

# -------- LLM clients / prompts (soft imports so advisor always loads) --------
# Specialized: Grok (x.ai)
try:
    from xai_client import grok_chat  # type: ignore
except Exception:
    def grok_chat(messages, temperature=0.2):
        return None  # graceful no-op

# Primary: DeepSeek (with timeout support)
try:
    from deepseek_client_timeout import deepseek_chat  # type: ignore
except Exception:
    try:
        from deepseek_client import deepseek_chat  # type: ignore
    except Exception:
        def deepseek_chat(messages, temperature=0.2, timeout=None):
            return None

# Fallback: OpenAI (with timeout support)
try:
    from openai_client_wrapper_timeout import openai_chat  # type: ignore
except Exception:
    try:
        from openai_client_wrapper import openai_chat  # type: ignore
    except Exception:
        def openai_chat(messages, temperature=0.2, timeout=None):
            return None

# (Optional) direct OpenAI import left intact for other modules that may import advisor
try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None  # type: ignore

try:
    from prompts import (  # type: ignore
        SYSTEM_INFO_PROMPT,
        GLOBAL_GUARDRAILS_PROMPT,
        ADVISOR_STRUCTURED_SYSTEM_PROMPT,
        ADVISOR_STRUCTURED_USER_PROMPT,
        ROLE_MATRIX_PROMPT,
        DOMAIN_PLAYBOOKS_PROMPT,
        TREND_CITATION_PROTOCOL,
        LOCATION_DATA_QUALITY_PROMPT,
    )
except Exception:
    # Minimal safe fallbacks; keep keys used in .format()
    SYSTEM_INFO_PROMPT = "You are Sentinel Advisor."
    GLOBAL_GUARDRAILS_PROMPT = ""
    ADVISOR_STRUCTURED_SYSTEM_PROMPT = ""
    ADVISOR_STRUCTURED_USER_PROMPT = "{input_data}"
    ROLE_MATRIX_PROMPT = ""
    DOMAIN_PLAYBOOKS_PROMPT = ""
    TREND_CITATION_PROTOCOL = ""
    LOCATION_DATA_QUALITY_PROMPT = ""

# Shared heuristics & guards
try:
    from risk_shared import (
        detect_domains,
        source_reliability,
        info_ops_flags,
        relevance_flags,  # sports/info-ops light guard
    )
except Exception:
    # safe fallbacks if risk_shared not present for any reason
    def detect_domains(text: str) -> List[str]: return []
    def source_reliability(source_name: Optional[str], source_url: Optional[str]) -> Tuple[str, str]: return ("Unknown", "")
    def info_ops_flags(text: str) -> List[str]: return []
    def relevance_flags(text: str) -> List[str]: return []

load_dotenv()

from config import CONFIG

OPENAI_API_KEY = CONFIG.llm.openai_api_key  # kept for compatibility elsewhere
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TEMPERATURE = CONFIG.llm.advisor_temperature

# ---------- Model usage tracking ----------
_model_usage_counts = {"deepseek": 0, "openai": 0, "grok": 0, "fallback": 0}

# ---------- Domain priority ----------
DOMAIN_PRIORITY = [
    "travel_mobility",
    "cyber_it",
    "digital_privacy_surveillance",
    "physical_safety",
    "civil_unrest",
    "terrorism",  # ensure terrorism-only cases get a specific primary action
    "kfr_extortion",
    "infrastructure_utilities",
    "environmental_hazards",
    "public_health_epidemic",
    "ot_ics",
    "info_ops_disinfo",
    "legal_regulatory",
    "business_continuity_supply",
    "insider_threat",
    "residential_premises",
    "emergency_medical",
    "counter_surveillance",
]

# ---------- Domain playbooks (programmatic one-liners) ----------
DOMAIN_PLAYBOOKS: Dict[str, List[str]] = {
    "physical_safety": [
        "Avoid poorly lit choke points after 20:00; use arterial roads and buddy-up on foot.",
        "Identify two safe havens within 200 m (hotel lobby, pharmacy, 24/7 store).",
    ],
    "civil_unrest": [
        "Bypass protest nodes via perimeter streets; plan detours 1–2 km from announced routes.",
    ],
    "terrorism": [
        "Minimize dwell in predictable queues; avoid glass-heavy facades and atriums.",
    ],
    "kfr_extortion": [
        "Vary routes/timings ±20 minutes; verify ride-hail (plate, name, one-time code).",
    ],
    "travel_mobility": [
        "Shift departures ±15–30 minutes; keep two route options; confirm curfew/checkpoints.",
    ],
    "infrastructure_utilities": [
        "Keep fuel ≥1/2 tank; carry water/cash; pre-map alt charging/power nodes.",
    ],
    "environmental_hazards": [
        "Avoid flood-prone underpasses; set AQI alerts; carry N95 if AQI > 100.",
    ],
    "public_health_epidemic": [
        "Prefer sealed/bottled water; carry ORS; avoid high-risk street food during spikes.",
    ],
    "cyber_it": [
        "Enforce passkeys/MFA; geo-fence admin logins; disable legacy auth for 72h.",
    ],
    "ot_ics": [
        "Isolate OT segments; block unsolicited remote access; restrict to break-glass accounts.",
    ],
    "digital_privacy_surveillance": [
        "Travel on a clean device; disable biometric unlock at ports; avoid untrusted Wi-Fi.",
    ],
    "info_ops_disinfo": [
        "Cross-check with two credible sources before acting; avoid resharing unverified alerts.",
    ],
    "legal_regulatory": [
        "Monitor curfew/checkpoint orders; screenshot official notices with timestamps.",
    ],
    "business_continuity_supply": [
        "Stage inventory; pre-book logistics windows; diversify last-mile carriers.",
    ],
    "insider_threat": [
        "Tighten badge controls; enforce 'no tailgating'; monitor privileged access anomalies.",
    ],
    "residential_premises": [
        "Harden perimeter lighting; door-control posture; store valuables away from master bedroom.",
    ],
    "emergency_medical": [
        "Know two nearest ER/urgent care; carry a compact trauma kit (tourniquet, hemostatic).",
    ],
    "counter_surveillance": [
        "Run an SDR with two deviations; note repeated sightings and anchor points.",
    ],
}

# ---------- Geographic validation ----------
# Import city_utils for enhanced location processing
try:
    from city_utils import fuzzy_match_city, normalize_city_country, get_country_for_city
except Exception:
    # Fallback implementations if city_utils is not available
    def fuzzy_match_city(text: str) -> Optional[str]:
        return None
    def normalize_city_country(city: str, country: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        return city.strip().title() if city else None, country.strip().title() if country else None
    def get_country_for_city(city: str) -> Optional[str]:
        return None

def _validate_location_match(query_location: str, alert_location_data: Dict[str, Any]) -> Tuple[float, str, str]:
    """
    Enhanced location matching using city_utils for better extraction and normalization.
    Returns: (match_score_0_100, matched_location_name, validation_warning)
    Penalizes heavily when query location doesn't match alert data location
    """
    if not query_location or not query_location.strip():
        return 0.0, "Unknown", "No query location provided"
    
    query_loc = query_location.strip()
    alert_city = (alert_location_data.get("city") or "").strip()
    alert_country = (alert_location_data.get("country") or "").strip()
    alert_region = (alert_location_data.get("region") or "").strip()
    
    # Use city_utils for enhanced location extraction from query
    query_city_match = fuzzy_match_city(query_loc)
    if not query_city_match:
        # Fallback: try first word as city name
        query_city_match = query_loc.split()[0] if query_loc else ""
    
    # Normalize both query and alert location data
    normalized_query_city, normalized_query_country = normalize_city_country(query_city_match or query_loc, None)
    normalized_alert_city, normalized_alert_country = normalize_city_country(alert_city, alert_country)
    
    # For query, use either the city match or try as country if city failed
    # This handles cases where user queries "France" (country) vs "Lyon" (city)
    query_as_city = (normalized_query_city or "").lower()
    query_as_country = ""
    if not query_as_city:
        # Try normalizing the original query as a country
        _, potential_country = normalize_city_country("", query_loc)
        query_as_country = (potential_country or query_loc).lower().strip()
    
    # Build comprehensive location strings for comparison
    alert_city_norm = (normalized_alert_city or "").lower()
    alert_country_norm = (normalized_alert_country or "").lower()
    alert_region_norm = alert_region.lower().strip()
    
    # Calculate match score with enhanced logic
    match_score = 0.0
    matched_components = []
    
    # Primary: Exact city match (highest score)
    if query_as_city and alert_city_norm and query_as_city == alert_city_norm:
        match_score = 100.0
        matched_components.append(f"city:{normalized_alert_city}")
    
    # Secondary: Fuzzy city match (substring)
    elif query_as_city and alert_city_norm and (
        query_as_city in alert_city_norm or alert_city_norm in query_as_city
    ):
        match_score = 90.0
        matched_components.append(f"city:{normalized_alert_city}")
    
    # Tertiary: Region match
    elif query_as_city and alert_region_norm and (
        query_as_city in alert_region_norm or alert_region_norm in query_as_city
    ):
        match_score = 75.0
        matched_components.append(f"region:{alert_region}")
    
    # Quaternary: Country match - both exact and substring
    elif (query_as_country or query_as_city) and alert_country_norm:
        query_for_country = query_as_country or query_as_city
        if (query_for_country == alert_country_norm or 
            query_for_country in alert_country_norm or 
            alert_country_norm in query_for_country):
            match_score = 60.0
            matched_components.append(f"country:{normalized_alert_country}")
    
    # Cross-check: Query city might be in alert country (geography knowledge)
    elif query_as_city and alert_country_norm:
        query_country = get_country_for_city(normalized_query_city or query_as_city)
        if query_country and query_country.lower() == alert_country_norm:
            match_score = 85.0
            matched_components.append(f"city_in_country:{normalized_query_city}→{normalized_alert_country}")
    
    # No meaningful match found
    if match_score == 0.0:
        match_score = 10.0  # Minimum score to indicate severe mismatch
        matched_components.append("no_match")
    
    # Build matched location name for display
    matched_name = ", ".join([
        normalized_alert_city or alert_city,
        alert_region,
        normalized_alert_country or alert_country
    ]).strip(", ") or "Unknown"
    
    # Generate warning for low confidence matches
    warning = ""
    if match_score < 30:
        warning = f"WARNING: Input data location '{matched_name}' does not match query location '{query_location}'. Recommendations are generic only."
        logger.warning(f"[Advisor] Geographic mismatch: query='{query_location}' vs data='{matched_name}' (score: {match_score:.1f})")
    elif match_score < 70:
        logger.info(f"[Advisor] Partial geographic match: query='{query_location}' vs data='{matched_name}' (score: {match_score:.1f}, components: {matched_components})")
    else:
        logger.info(f"[Advisor] Strong geographic match: query='{query_location}' vs data='{matched_name}' (score: {match_score:.1f}, components: {matched_components})")
    
    return match_score, matched_name, warning

# ---------- Role inference data ----------
ROLE_KEYWORDS: Dict[str, List[str]] = {
    "traveler": ["traveler","tourist","visitor","student","backpacker","vacation","holiday"],
    "executive": ["executive","exec","ceo","c-suite","vip","founder","chairman","board"],
    "logistics_driver": ["driver","logistics","truck","fleet","delivery","last-mile","dispatcher"],
    "it_secops": ["it","secops","security engineer","admin","administrator","ciso","sysadmin","sre","devops"],
    "ngo_aid": ["ngo","aid","humanitarian","non-profit","charity","relight","mission"],
    "family_parent_teen": ["family","parent","mom","dad","teen","child","children","kids"],
    "journalist": ["journalist","reporter","press","media","photojournalist","stringer","pi"],
    "diplomat": ["diplomat","embassy","consular","consulate","mission","attaché"],
    "ops_manager": ["ops manager","operations","site lead","plant manager","facilities"],
}
ROLE_DOMAIN_PREF: Dict[str, List[str]] = {
    "traveler": ["travel_mobility","physical_safety","digital_privacy_surveillance","residential_premises","emergency_medical"],
    "executive": ["travel_mobility","physical_safety","counter_surveillance","digital_privacy_surveillance","kfr_extortion"],
    "logistics_driver": ["travel_mobility","infrastructure_utilities","business_continuity_supply","physical_safety"],
    "it_secops": ["cyber_it","ot_ics","business_continuity_supply","digital_privacy_surveillance"],
    "ngo_aid": ["travel_mobility","civil_unrest","environmental_hazards","emergency_medical"],
    "family_parent_teen": ["physical_safety","digital_privacy_surveillance","residential_premises","emergency_medical","travel_mobility"],
    "journalist": ["counter_surveillance","digital_privacy_surveillance","travel_mobility","physical_safety","info_ops_disinfo"],
    "diplomat": ["legal_regulatory","travel_mobility","digital_privacy_surveillance","civil_unrest"],
    "ops_manager": ["business_continuity_supply","infrastructure_utilities","physical_safety","cyber_it"],
}
PERSONAL_DOMAIN_ALIAS = {
    "personal_security": ["physical_safety","residential_premises"]
}

# ---------- Output guard ----------
# FIXED: Patterns now allow flexible spacing and ensure proper formatting
REQUIRED_HEADERS = [
    r"^ALERT\s*—", 
    r"^BULLETPOINT RISK SUMMARY\s*—",
    r"^TRIGGERS\s*/\s*KEYWORDS\s*—", 
    r"^CATEGORIES\s*/\s*SUBCATEGORIES\s*—",
    r"^SOURCES\s*—", 
    r"^REPORTS ANALYZED\s*—", 
    r"^CONFIDENCE\s*—",
    r"^WHAT TO DO NOW\s*—", 
    r"^HOW TO PREPARE\s*—",
    r"^ROLE-SPECIFIC ACTIONS\s*—", 
    r"^DOMAIN PLAYBOOK HITS\s*—",
    r"^FORECAST\s*—", 
    r"^EXPLANATION\s*—", 
    r"^ANALYST CTA\s*—"
]

def ensure_sections(advisory: str) -> str:
    """Simplified: only add section if completely missing, with proper spacing"""
    out = advisory.strip()
    lines = out.split('\n')
    
    for pat in REQUIRED_HEADERS:
        # Extract header text from pattern more reliably
        header_text = re.sub(r'[\^\$\s\\]', '', pat).replace('—', '').strip()
        header_text = re.sub(r'(?<!^)([A-Z])([A-Z]+)', r' \1\2', header_text)  # Add spaces
        header_text = header_text.replace('  ', ' ').strip() + ' —'  # Ensure spacing
        
        # Check if section header exists
        section_idx = -1
        for i, line in enumerate(lines):
            if re.search(pat, line, re.IGNORECASE):
                section_idx = i
                break
        
        if section_idx == -1:
            # Section completely missing - add it with proper spacing
            out += f"\n\n{header_text}\n• [auto] Section added (no content)"
            lines = out.split('\n')  # Rebuild lines for next iteration
    
    return out

def ensure_has_playbook_or_alts(advisory: str, playbook_hits: dict, alts: list) -> str:
    """
    Domain-aware guard: only consider domain-tagged lines as satisfying the 'playbook present' check.
    Prevents role tags like [Traveler] from skipping the additions.
    """
    out = advisory

    # Add playbook section if missing and we actually have hits
    if ("DOMAIN PLAYBOOK HITS —" not in out) and playbook_hits:
        out += "\n\nDOMAIN PLAYBOOK HITS —\n" + "\n".join(
            f"• [{d}] {tip}" for d, tips in playbook_hits.items() for tip in tips
        )

    # If no domain-tagged lines present, ensure we at least add ALTERNATIVES
    has_domain_tag = any(f'[{d}]' in out for d in (playbook_hits or {}).keys())
    if ("ALTERNATIVES —" not in out) and (alts and not has_domain_tag):
        out += "\n\nALTERNATIVES —\n" + "\n".join(f"• {a}" for a in alts)

    return out

def clean_auto_sections(advisory: str) -> str:
    """Remove placeholders, empty sections, and fix spacing with surgical precision"""
    # Remove auto-added lines
    cleaned = re.sub(r"\n?• \[auto\] Section added \(no content\)", "", advisory)
    
    # Remove orphaned headers (header followed by nothing or another header)
    # Pattern: HEADER —\n\n(next is HEADER or end)
    cleaned = re.sub(
        r'\n\n([A-Z][A-Za-z\s/]+?)\s*—\s*\n(?=\n|[A-Z][A-Za-z\s/]+?—|\Z)',
        '', 
        cleaned
    )
    
    # Fix missing spaces after section headers
    cleaned = re.sub(r'([A-Z][A-Za-z\s/]+?—)([A-Z])', r'\1 \2', cleaned)
    
    # Ensure exactly one space before dash
    cleaned = re.sub(r'\s*—\s*', ' — ', cleaned)
    
    return cleaned.strip()

def strip_excessive_blank_lines(text: str) -> str:
    # Replace 3+ consecutive newlines with exactly 2
    # Also clean up trailing whitespace
    lines = [line.rstrip() for line in text.split('\n')]
    result = []
    empty_streak = 0
    
    for line in lines:
        if not line.strip():
            empty_streak += 1
            if empty_streak <= 2:  # Keep max 2 empty lines
                result.append('')
        else:
            empty_streak = 0
            result.append(line)
    
    # Remove leading/trailing empty lines
    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()
    
    return '\n'.join(result)

def trim_verbose_explanation(advisory: str) -> str:
    """
    Post-process advisory to trim verbose EXPLANATION sections.
    Keeps first 150 chars of trend line and adds confidence note.
    """
    lines = advisory.split('\n')
    explanation_start = -1
    
    # Find EXPLANATION section
    for i, line in enumerate(lines):
        if re.match(r'^EXPLANATION\s*—', line):
            explanation_start = i
            break
    
    if explanation_start == -1:
        return advisory
    
    # Find next section or end
    next_section = len(lines)
    for i in range(explanation_start + 1, len(lines)):
        if re.match(r'^[A-Z][A-Z\s/]+ —', lines[i]):
            next_section = i
            break
    
    # Extract explanation content
    explanation_lines = lines[explanation_start + 1:next_section]
    
    # If explanation is verbose (>3 lines or >200 chars total), trim it
    total_chars = sum(len(line) for line in explanation_lines)
    if len(explanation_lines) > 3 or total_chars > 200:
        # Keep the trend line (usually first bullet) but truncate
        trend_bullet = explanation_lines[0] if explanation_lines else "• Analysis based on current patterns."
        if trend_bullet.startswith("• "):
            trend_content = trend_bullet[2:]  # Remove bullet
            if len(trend_content) > 150:
                trend_content = trend_content[:150] + "..."
            new_explanation = [
                f"• {trend_content}",
                "• Confidence adjusted for location precision and source reliability."
            ]
        else:
            new_explanation = [
                "• Analysis based on current threat patterns and geographic factors.",
                "• Confidence adjusted for location precision and source reliability."
            ]
        
        # Rebuild lines
        new_lines = (
            lines[:explanation_start + 1] +  # Everything up to and including "EXPLANATION —"
            new_explanation +               # Trimmed explanation
            lines[next_section:]            # Everything after explanation
        )
        return '\n'.join(new_lines)
    
    return advisory

# ---------- JSON serialization helper for Decimal ----------
def _json_serialize(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

# ---------- Utilities ----------
def _first_present(domains: List[str]) -> Optional[str]:
    for d in DOMAIN_PRIORITY:
        if d in domains:
            return d
    return domains[0] if domains else None

def _infer_roles(profile_data: Optional[Dict[str, Any]], user_message: str) -> List[str]:
    text = " ".join([
        (profile_data or {}).get("role",""),
        (profile_data or {}).get("profession",""),
        (profile_data or {}).get("user_type",""),
        user_message or ""
    ]).lower()
    roles: List[str] = []
    for role, kws in ROLE_KEYWORDS.items():
        if any(k in text for k in kws):
            roles.append(role)
    if not roles:
        roles.append("traveler")
    return roles

def _role_actions_for(domains: List[str], role: str) -> List[str]:
    dset = set(domains)
    out: List[str] = []
    if role == "traveler":
        out += [
            "NOW: adjust departures ±15–30 min; request hotel room floors 2–4 near stairwell; identify two safe havens within 200 m.",
            "PREP: offline maps; local SIM/eSIM; embassy contact; set check-in protocol (time + contact + codeword).",
        ]
        if "digital_privacy_surveillance" in dset or "cyber_it" in dset:
            out.append("DIGITAL: travel with a clean device; disable biometric unlock at borders; use passkeys/VPN.")
    elif role == "executive":
        out += [
            "NOW: stagger routes/vehicles; minimize dwell time; use hardened meeting sites with controlled access.",
            "PREP: protective intel watch; define red/amber/green posture; pre-brief driver and venue security.",
        ]
        if "kfr_extortion" in dset or "counter_surveillance" in dset:
            out.append("ANTI-KIDNAP/CSURV: vary patterns by ±20 min; run SDR with two deviations; verify ride-hail by code.")
    elif role == "logistics_driver":
        out += [
            "NOW: avoid last-mile hotspots; fuel/refuel outside risk zones; maintain dashcam with 72h retention.",
            "PREP: two alternate yards; geofenced SOPs; paper route sheets for power/telecom outages.",
        ]
    elif role == "it_secops":
        out += [
            "NOW: enforce passkeys/MFA; geo-fence admin; disable legacy auth for 72h; review high-risk app tokens.",
            "PREP: EDR thresholds; phishing drills; privileged access review; OT segmentation check.",
        ]
    elif role == "ngo_aid":
        out += [
            "NOW: deconflict with local authorities; validate convoy timings; stage at safer hubs.",
            "PREP: liaison list; medevac and shelter-in-place plans; radio/alt comms check.",
        ]
    elif role == "family_parent_teen":
        out += [
            "NOW: enable live location sharing to guardians; use pickup passwords; avoid isolated choke points.",
            "PREP: parental controls; privacy lockdown on socials; doxxing shield; ICE card.",
        ]
    elif role == "journalist":
        out += [
            "NOW: run SDR; keep hands free; minimize time near crowd cores/lines; vet fixers.",
            "PREP: comms compartmentalization; device hardening (clean phone, app minimization); backup power and PPE.",
        ]
    elif role == "diplomat":
        out += [
            "NOW: review curfew/checkpoint orders; coordinate moves with host-nation police; avoid protest vectors.",
            "PREP: comms with mission control; secure convoy SOP; legal liaison contacts ready.",
        ]
    elif role == "ops_manager":
        out += [
            "NOW: confirm stop-work criteria; staff safety check; shift critical ops to redundant node if needed.",
            "PREP: tabletop top-3 risks; vendor failover SLAs; offline runbooks; muster points verified.",
        ]
    return out

def _programmatic_playbook_hits(domains: List[str]) -> Dict[str, List[str]]:
    hits: Dict[str, List[str]] = {}
    for d in domains:
        tips = DOMAIN_PLAYBOOKS.get(d, [])
        if tips:
            hits[d] = tips[:2]
    return hits

def _filter_hits_by_profile(hits: Dict[str, List[str]], roles: List[str]) -> Dict[str, List[str]]:
    if not roles:
        return hits
    preferred_domains: List[str] = []
    for role in roles:
        preferred_domains += ROLE_DOMAIN_PREF.get(role, [])
    expanded_pref: List[str] = []
    for d in preferred_domains:
        if d in PERSONAL_DOMAIN_ALIAS:
            expanded_pref += PERSONAL_DOMAIN_ALIAS[d]
        else:
            expanded_pref.append(d)
    if not expanded_pref:
        return hits
    preferred, others = {}, {}
    for d, tips in hits.items():
        (preferred if d in expanded_pref else others)[d] = tips
    ordered = {**preferred, **others}
    return {k: ordered[k] for k in list(ordered.keys())[:6]} or hits

def _alternatives_if_needed(alert: Dict[str, Any]) -> List[str]:
    d = set(alert.get("domains") or [])
    alts: List[str] = []
    # Core travel + unrest/safety/infrastructure
    if "travel_mobility" in d and ({"civil_unrest","physical_safety","infrastructure_utilities"} & d):
        alts.append("Alt 1 — Timing & Route: depart ±30 min from peak; use ring/perimeter road (e.g., A12) vs central artery; risk: +10–20 min travel.")
        alts.append("Alt 2 — Method & Staging: vetted car service with driver wait; stage at secure hotel near secondary exit; risk: higher cost/limited availability after 22:00.")
    # Travel + digital privacy/cyber (border/device checks)
    if "travel_mobility" in d and ({"digital_privacy_surveillance","cyber_it"} & d):
        alts.append("Alt 3 — Border Digital Posture: travel with a clean phone; disable biometrics; sign out of sensitive accounts; paper/eWallet boarding; risk: limited offline docs.")
        alts.append("Alt 4 — Connectivity Method: use carrier eSIM and personal hotspot instead of public Wi-Fi; risk: data costs, dependent on coverage.")
    # Travel + environmental
    if "travel_mobility" in d and "environmental_hazards" in d:
        alts.append("Alt 5 — Weather Routing: shift to daylight; avoid low underpasses/floodways; check closures; risk: fewer time windows.")
        alts.append("Alt 6 — Mode Swap: rail/metro segments to bypass flood zones; risk: crowding/schedule variability.")
    # Travel + KFR
    if "travel_mobility" in d and "kfr_extortion" in d:
        alts.append("Alt 7 — Secure Transport: switch to vetted provider with driver ID pre-share; lock discipline; risk: cost, lead time.")
        alts.append("Alt 8 — Movement Patterning: vary windows by ±20 min; use busy forecourts for pickup; risk: added coordination.")
    # Cyber BEC + travel
    if "cyber_it" in d and "travel_mobility" in d:
        alts.append("Alt 9 — Payment Control: pre-approved vendor list + out-of-band voice-confirm for wire changes; risk: slower approvals.")
        alts.append("Alt 10 — Account Hygiene: passkeys on finance apps; geo-fence admin logins; disable legacy auth; risk: access friction for travelers.")
    # Legal/regulatory + travel
    if "legal_regulatory" in d and "travel_mobility" in d:
        alts.append("Alt 11 — Curfew Windowing: schedule moves inside legal windows; carry employer letters; risk: constrained operations.")
        alts.append("Alt 12 — Permitted Corridors: use officially permitted routes; carry ID/permits; risk: checkpoint delays.")
    return alts

def _monitoring_cadence(trend_direction: str, anomaly: bool, roles: List[str], p_future: Optional[float]) -> str:
    base = 12
    if anomaly or trend_direction == "increasing":
        base = 6
    if p_future and p_future >= 0.7:
        base = 4
    if "journalist" in roles or "executive" in roles:
        base = min(base, 6)
    return f"{base}h"

def _normalize_sources(sources: Any) -> List[Dict[str, str]]:
    out = []
    if isinstance(sources, list):
        for s in sources:
            if isinstance(s, dict):
                name = s.get("name") or s.get("source") or "Source"
                link = s.get("link") or s.get("url")
                item = {"name": name}
                if link:
                    item["link"] = link
                out.append(item)
            elif isinstance(s, str):
                out.append({"name": s})
    return out

def _join_text(*parts: Any) -> str:
    return " ".join([str(p) for p in parts if p])

# ---------- Trend-citation line ----------
def _build_trend_citation_line(alert: Dict[str, Any]) -> Tuple[str, str]:
    td = str(alert.get("trend_direction") or "stable")
    br = alert.get("baseline_ratio")
    ic30 = alert.get("incident_count_30d")
    anom = alert.get("anomaly_flag", alert.get("is_anomaly"))
    cat = alert.get("category") or alert.get("threat_label") or "risk"
    p_future = alert.get("future_risk_probability")

    bits = []
    if td: bits.append(f"trend_direction={td}")
    if isinstance(br, (int, float)): bits.append(f"baseline={round(float(br), 2)}x")
    elif hasattr(br, 'to_eng_string'):  # Decimal case
        bits.append(f"baseline={round(float(br), 2)}x")
    if isinstance(ic30, int): bits.append(f"incident_count_30d={ic30}")
    if isinstance(anom, bool) and anom: bits.append("anomaly_flag=true")
    if isinstance(p_future, (int, float)): bits.append(f"p_next48h={round(float(p_future), 2)}")
    x = ", ".join(bits) if bits else "recent patterns"

    domains = alert.get("domains") or []
    primary = _first_present(domains)
    category = (alert.get("category") or "").lower()
    title_text = (alert.get("title", "") + " " + alert.get("summary", "")).lower()

    # Smart routing based on category, domains, and content
    action = "tighten posture now (route alternatives, safe havens, MFA/passkeys) and review in 12h"
    
    # Prioritize specific mobility/infrastructure threats
    if (primary == "travel_mobility" or 
        any(word in title_text for word in ["airport", "railway", "transport", "border", "road closure", "bridge"])):
        action = "shift departures ±30 minutes, reroute via secondary arterials, and avoid choke points until checkpoint density <1/day or curfews lift"
    
    # Cyber-specific actions
    elif (primary == "cyber_it" or 
          "cyber" in category or
          any(word in title_text for word in ["hack", "breach", "ransomware", "malware", "cyber"])):
        action = "enforce passkeys/MFA, geo-fence admin logins, and disable legacy auth for 72h"
    
    # Surveillance/privacy concerns  
    elif (primary == "digital_privacy_surveillance" or
          any(word in title_text for word in ["surveillance", "privacy", "monitoring", "tracking"])):
        action = "travel on a clean device, disable biometric unlock at ports, and avoid untrusted Wi-Fi"
    
    # Physical safety threats
    elif (primary == "physical_safety" or 
          "crime" in category or
          any(word in title_text for word in ["violence", "attack", "shooting", "assault", "murder"])):
        action = "avoid poorly lit choke points after 20:00, use well-lit arterials, and stage near 24/7 venues"
    
    # Civil unrest
    elif (primary == "civil_unrest" or
          "civil unrest" in category or  
          any(word in title_text for word in ["protest", "riot", "demonstration", "unrest"])):
        action = "bypass protest nodes via perimeter streets and adjust movement to off-peak windows"
    
    # Terrorism threats
    elif (primary == "terrorism" or
          "terrorism" in category or
          any(word in title_text for word in ["terrorism", "terrorist", "bomb", "explosion", "ied"])):
        action = "avoid crowded public venues, use hardened transport, and maintain 360° situational awareness"
    
    # Infrastructure/utility disruptions
    elif (primary == "infrastructure_utilities" or
          "infrastructure" in category or
          any(word in title_text for word in ["power", "electricity", "outage", "blackout", "grid"])):
        action = "secure backup power/comms, pre-stage supplies, and plan offline contingencies for 24-48h"
    
    # Health/epidemic concerns
    elif (any(word in title_text for word in ["epidemic", "outbreak", "virus", "contamination", "health"])):
        action = "follow health protocols, secure clean water/supplies, and monitor official health advisories"
    
    # OT/ICS specific
    elif primary == "ot_ics":
        action = "isolate OT segments, block external remote access, and restrict to break-glass accounts"

    trend_line = f"Because {x} for {cat}, do {action}."
    return trend_line, action

# ---------- Multi-alert synthesis (predictive/proactive) ----------
def _aggregate_alerts(alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge up to top-3 by score into one advisory context:
      - keep highest score/label/confidence
      - union domains (cap 8), union sources (cap 6)
      - max trend (anomaly true if any true), max future_risk_probability
    Falls back to first if list empty.
    """
    if not alerts:
        return {}
    
    # FIXED: Proper type conversion for numerical comparisons
    def _get_sort_key(a):
        try:
            # Convert score to float safely
            score_str = a.get("score")
            score = float(score_str) if score_str is not None else 0.0
        except (TypeError, ValueError):
            score = 0.0
            
        try:
            # Convert future_risk_probability to float safely
            future_risk_str = a.get("future_risk_probability")
            future_risk = float(future_risk_str) if future_risk_str is not None else 0.0
        except (TypeError, ValueError):
            future_risk = 0.0
            
        return (score, future_risk)
    
    # Sort by score desc, then future_risk_probability
    top = sorted(alerts, key=_get_sort_key, reverse=True)[:3]
    base = dict(top[0])
    
    # domains
    dset = []
    for a in top:
        for d in a.get("domains") or []:
            if d not in dset:
                dset.append(d)
    base["domains"] = dset[:8]
    
    # sources
    src = []
    for a in top:
        for s in a.get("sources") or []:
            if isinstance(s, dict):
                item = {"name": s.get("name"), "link": s.get("link")}
            else:
                item = {"name": str(s)}
            if item not in src:
                src.append(item)
    base["sources"] = src[:6]
    
    # aggregates - FIXED: Ensure proper type conversion
    try:
        base["score"] = float(top[0].get("score", base.get("score"))) if top[0].get("score") is not None else base.get("score"
        )
    except (TypeError, ValueError):
        base["score"] = base.get("score")
        
    base["label"] = top[0].get("label", base.get("label"))
    
    try:
        base["confidence"] = float(top[0].get("confidence", base.get("confidence"))) if top[0].get("confidence") is not None else base.get("confidence")
    except (TypeError, ValueError):
        base["confidence"] = base.get("confidence")
        
    base["anomaly_flag"] = any(a.get("anomaly_flag", a.get("is_anomaly")) for a in top)
    
    # FIXED: Convert future_risk_probability to float before max comparison
    future_risks = []
    for a in top:
        risk_val = a.get("future_risk_probability")
        try:
            if risk_val is not None:
                future_risks.append(float(risk_val))
        except (TypeError, ValueError):
            continue
    base["future_risk_probability"] = max(future_risks) if future_risks else 0
    
    # keep strongest trend if any increasing present
    trends = [str(a.get("trend_direction") or "stable") for a in top]
    base["trend_direction"] = "increasing" if "increasing" in trends else ("decreasing" if "decreasing" in trends else trends[0])
    return base

# ---------- Soft relevance guard ----------
def _is_soft_irrelevant(alert: Dict[str, Any]) -> bool:
    """
    If text looks like sports context AND there are no meaningful domains, skip advising.
    Only used when multiple alerts are passed; single-alert flows still advise.
    """
    t = _join_text(alert.get("title"), alert.get("summary"))
    flags = relevance_flags(t) or []
    if "sports_context" in flags and not (alert.get("domains") or []):
        return True
    return False

# ---------- Input payload for LLM ----------
def _build_input_payload(alert: Dict[str, Any], user_message: str, profile_data: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str], Dict[str, List[str]]]:
    roles = _infer_roles(profile_data, user_message)
    domains = alert.get("domains") or []
    
    # Backfill domains if missing
    if not domains:
        t = _join_text(alert.get("title"), alert.get("summary"))
        domains = detect_domains(t) or []
        alert["domains"] = domains

    # NEW: Validate location match and calculate precision
    location_match_score, matched_location, location_warning = _validate_location_match(
        user_message, 
        {
            "city": alert.get("city"),
            "region": alert.get("region"), 
            "country": alert.get("country")
        }
    )
    
    # NEW: Calculate location precision (street-level vs city-level)
    has_coordinates = bool(alert.get("latitude") and alert.get("longitude"))
    has_specific_venue = bool(alert.get("venue") or alert.get("address"))
    location_precision = "high" if has_coordinates else ("medium" if has_specific_venue else "low")
    
    # NEW: Check statistical validity of trend data
    incident_count = alert.get("incident_count_30d", 0)
    baseline_ratio = alert.get("baseline_ratio", 1.0)
    is_statistically_valid = incident_count is not None and incident_count >= 5
    
    # NEW: Adjust confidence based on location match and data quality
    original_confidence = float(alert.get("confidence", 0.5))
    
    # Apply location match penalty
    location_penalty = (100 - location_match_score) / 100.0  # 0.0 to 0.9
    adjusted_confidence = original_confidence * (1.0 - location_penalty * 0.7)  # 70% max penalty
    
    # Apply data quality penalty
    if not is_statistically_valid:
        adjusted_confidence *= 0.6  # 40% penalty for insufficient data
        logger.warning(f"[Advisor] Insufficient data: incident_count_30d={incident_count} (<5)")
    
    # Apply precision penalty
    if location_precision == "low":
        adjusted_confidence *= 0.8  # 20% penalty for low precision
    
    # Floor confidence at 10% to avoid 0% confidence
    final_confidence = max(0.1, min(1.0, adjusted_confidence))

    raw_hits = _programmatic_playbook_hits(domains)
    hits = _filter_hits_by_profile(raw_hits, roles)

    role_blocks: Dict[str, List[str]] = {}
    for r in roles:
        role_blocks[r] = _role_actions_for(domains, r)

    anomaly = alert.get("anomaly_flag", alert.get("is_anomaly"))
    next_review = _monitoring_cadence(alert.get("trend_direction") or "stable", bool(anomaly), roles, alert.get("future_risk_probability"))

    # FIXED: Convert Decimal to float for JSON serialization
    def _convert_decimal_to_float(obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return obj

    # Convert all Decimal values in alert to float
    processed_alert = {}
    for key, value in alert.items():
        if isinstance(value, decimal.Decimal):
            processed_alert[key] = float(value)
        else:
            processed_alert[key] = value

    # NEW: Add validation metadata to payload
    payload = {
        "region": processed_alert.get("region") or processed_alert.get("city") or processed_alert.get("country"),
        "city": processed_alert.get("city"),
        "country": processed_alert.get("country"),
        "category": processed_alert.get("category") or processed_alert.get("threat_label"),
        "subcategory": processed_alert.get("subcategory") or "Unspecified",
        "label": processed_alert.get("label"),
        "score": _convert_decimal_to_float(processed_alert.get("score")),
        "confidence_original": original_confidence,  # Keep original for reference
        "confidence": final_confidence,  # Use adjusted confidence
        "domains": domains,
        "reports_analyzed": processed_alert.get("reports_analyzed") or processed_alert.get("num_reports") or 1,
        "sources": _normalize_sources(processed_alert.get("sources") or []),
        "incident_count_30d": processed_alert.get("incident_count_30d") if processed_alert.get("incident_count_30d") is not None else "n/a",
        "recent_count_7d": processed_alert.get("recent_count_7d") if processed_alert.get("recent_count_7d") is not None else "n/a",
        "baseline_avg_7d": processed_alert.get("baseline_avg_7d") if processed_alert.get("baseline_avg_7d") is not None else "n/a",
        "baseline_ratio": _convert_decimal_to_float(processed_alert.get("baseline_ratio")) if processed_alert.get("baseline_ratio") is not None else "n/a",
        "trend_direction": processed_alert.get("trend_direction") if processed_alert.get("trend_direction") is not None else "stable",
        "anomaly_flag": anomaly if anomaly is not None else False,
        "cluster_id": processed_alert.get("cluster_id"),
        "early_warning_indicators": processed_alert.get("early_warning_indicators") or [],
        "future_risk_probability": _convert_decimal_to_float(processed_alert.get("future_risk_probability")),
        "domain_playbook_hits": hits,
        "alternatives": _alternatives_if_needed(processed_alert),
        "roles": roles,
        "role_actions": role_blocks,
        "next_review_hours": next_review,
        "profile_data": profile_data or {},
        "user_message": user_message,
        "incident_count": processed_alert.get("incident_count", processed_alert.get("incident_count_30d", "n/a")),
        "threat_type": processed_alert.get("category", processed_alert.get("threat_type", "risk")),
        # NEW: Location validation metadata
        "location_match_score": location_match_score,
        "location_precision": location_precision,
        "location_validation_warning": location_warning,
        "data_statistically_valid": is_statistically_valid,
        "location_matched_name": matched_location,
    }
    return payload, roles, hits

def _sources_reliability_lines(sources: List[Dict[str, str]]) -> List[str]:
    out: List[str] = []
    for s in sources or []:
        name = s.get("name")
        link = s.get("link")
        rating, reason = source_reliability(name, link)
        tag = f"{rating}" if rating else "Unknown"
        reason_str = f" — {reason}" if reason else ""
        if link:
            out.append(f"- {name} ({tag}) {link}{reason_str}")
        else:
            out.append(f"- {name} ({tag}){reason_str}")
    return out

def _add_data_provenance_section(advisory: str, input_data: Dict[str, Any]) -> str:
    """
    Adds a DATA PROVENANCE section showing location match and data quality warnings
    This exposes the Budapest->Cairo mismatch to the user
    """
    warning = input_data.get("location_validation_warning", "")
    precision = input_data.get("location_precision", "unknown")
    match_score = input_data.get("location_match_score", 0)
    is_valid = input_data.get("data_statistically_valid", False)
    
    if not warning and match_score >= 80 and is_valid:
        # Everything looks good, no need for extra section
        return advisory
    
    provenance_lines = ["\n\nDATA PROVENANCE —"]
    
    if warning:
        provenance_lines.append(f"⚠️ {warning}")
    
    provenance_lines.append(f"- Location Precision: {precision} (coordinates: {'yes' if precision == 'high' else 'no'})")
    provenance_lines.append(f"- Location Match Score: {match_score}/100")
    
    if not is_valid:
        incident_count = input_data.get("incident_count_30d", 0)
        provenance_lines.append(f"- Data Volume: INSUFFICIENT (incident_count_30d={incident_count} < 5)")
        provenance_lines.append("- Recommendations are generic pattern-based only")
    
    # Add sources with clear reliability
    sources = input_data.get("sources") or []
    if sources:
        provenance_lines.append("- Sources Used:")
        for s in sources:
            name = s.get("name", "Unknown")
            link = s.get("link", "")
            provenance_lines.append(f"  • {name} {link}")
    
    # Insert before EXPLANATION section or at end if not found
    lines = advisory.split('\n')
    explanation_idx = -1
    for i, line in enumerate(lines):
        if re.match(r'^EXPLANATION\s*—', line):
            explanation_idx = i
            break
    
    if explanation_idx != -1:
        lines.insert(explanation_idx, "\n".join(provenance_lines))
    else:
        lines.append("\n".join(provenance_lines))
    
    return "\n".join(lines)

# ---------- Debugging utilities ----------
def get_llm_routing_stats():
    """
    Get comprehensive LLM routing statistics for monitoring and debugging.
    Useful for understanding failure patterns and provider reliability.
    """
    total_requests = sum(_model_usage_counts.values())
    stats = {
        "total_requests": total_requests,
        "usage_counts": dict(_model_usage_counts),
        "success_rate": round((total_requests - _model_usage_counts.get("fallback", 0) - _model_usage_counts.get("handle_query_fallback", 0)) / max(total_requests, 1) * 100, 2) if total_requests > 0 else 0,
        "primary_provider_success": round(_model_usage_counts.get("deepseek", 0) / max(total_requests, 1) * 100, 2) if total_requests > 0 else 0,
        "fallback_rate": round((_model_usage_counts.get("fallback", 0) + _model_usage_counts.get("handle_query_fallback", 0)) / max(total_requests, 1) * 100, 2) if total_requests > 0 else 0
    }
    return stats

def reset_llm_routing_stats():
    """Reset LLM routing statistics (useful for testing or periodic monitoring)"""
    global _model_usage_counts
    _model_usage_counts = {"deepseek": 0, "openai": 0, "grok": 0, "fallback": 0, "handle_query_fallback": 0}
    logger.info("[Advisor] LLM routing statistics reset")

def log_llm_routing_summary():
    """
    Log a comprehensive summary of LLM routing performance.
    Call this periodically to understand provider reliability patterns.
    """
    stats = get_llm_routing_stats()
    logger.info("="*60)
    logger.info("[Advisor] LLM ROUTING PERFORMANCE SUMMARY")
    logger.info("="*60)
    logger.info(f"Total requests: {stats['total_requests']}")
    logger.info(f"Overall success rate: {stats['success_rate']}%")
    logger.info(f"Primary provider (DeepSeek) success: {stats['primary_provider_success']}%")
    logger.info(f"Fallback rate: {stats['fallback_rate']}%")
    logger.info("Provider breakdown:")
    for provider, count in stats['usage_counts'].items():
        percentage = round(count / max(stats['total_requests'], 1) * 100, 1)
        logger.info(f"  {provider}: {count} requests ({percentage}%)")
    
    if stats['fallback_rate'] > 10:
        logger.warning(f"⚠️  High fallback rate ({stats['fallback_rate']}%) - investigate provider issues!")
    if stats['primary_provider_success'] < 50:
        logger.warning(f"⚠️  Low primary provider success ({stats['primary_provider_success']}%) - check DeepSeek connectivity!")
    
    logger.info("="*60)

# ---------- Public wrappers ----------
def render_advisory(alert: Dict[str, Any], user_message: str, profile_data: Optional[Dict[str, Any]] = None, plan: str = "FREE") -> str:
    trend_line, action = _build_trend_citation_line(alert)
    input_data, roles, hits = _build_input_payload(alert, user_message, profile_data)
    input_data["trend_citation_line"] = trend_line
    input_data["action"] = action
    input_data["specific_action"] = action  # For prompts using {specific action}

    # Geographic validation - check if query location matches alert location
    geographic_warning = ""
    location_match_score = 0
    location_precision = "unknown"
    data_statistically_valid = False
    
    if profile_data and profile_data.get("location"):
        query_location = profile_data.get("location")
        alert_location_data = {
            "city": alert.get("city"),
            "country": alert.get("country"), 
            "region": alert.get("region")
        }
        location_match_score, matched_name, warning = _validate_location_match(query_location, alert_location_data)
        if warning:
            geographic_warning = warning
            input_data["geographic_warning"] = warning
            
        # Extract additional location data from input_data if available
        location_precision = input_data.get("location_precision", "unknown")
        data_statistically_valid = input_data.get("data_statistically_valid", False)
        
        input_data["geographic_match_score"] = location_match_score
        logger.info(f"[Advisor] Geographic validation: score={location_match_score}, warning={bool(warning)}")

    # NEW: Inject location validation constraints for LLM enforcement
    input_data["llm_constraints"] = {
        "location_match_score": location_match_score,
        "location_precision": location_precision,
        "low_data_volume": not data_statistically_valid,
        "enforce_generic_recommendations": location_match_score < 30,
        "max_explanation_bullets": 3,
        "max_explanation_chars": 150,
        "location_mismatch_detected": location_match_score < 30,
        "data_quality_concerns": not data_statistically_valid or location_match_score < 50
    }

    # Predictive tone nudges from future_risk_probability
    p_future = input_data.get("future_risk_probability")
    if isinstance(p_future, (int, float)):
        if p_future >= 0.85:
            input_data["forecast_tone"] = "imminent"
        elif p_future >= 0.65:
            input_data["forecast_tone"] = "likely"
        elif p_future >= 0.45:
            input_data["forecast_tone"] = "possible"
        else:
            input_data["forecast_tone"] = "low"

    # Info-ops/sensational flags (for visibility; do not block advising)
    text_blob = _join_text(alert.get("title"), alert.get("summary"))
    input_data["info_ops_flags"] = info_ops_flags(text_blob)

    system_content = "\n\n".join([
        SYSTEM_INFO_PROMPT,
        GLOBAL_GUARDRAILS_PROMPT,
        TREND_CITATION_PROTOCOL,
        ROLE_MATRIX_PROMPT,
        DOMAIN_PLAYBOOKS_PROMPT,
        ADVISOR_STRUCTURED_SYSTEM_PROMPT,
    ])

    # FIXED: Use custom JSON serializer for Decimal objects
    user_content = ADVISOR_STRUCTURED_USER_PROMPT.format(
        user_message=user_message,
        input_data=json.dumps(input_data, ensure_ascii=False, default=_json_serialize),
        trend_citation_line=trend_line,
        trend_direction=input_data.get("trend_direction", "stable"),
        incident_count_30d=input_data.get("incident_count_30d", "n/a"),
        incident_count=input_data.get("incident_count", input_data.get("incident_count_30d", "n/a")),
        threat_type=input_data.get("threat_type", "risk"),
        recent_count_7d=input_data.get("recent_count_7d", "n/a"),
        baseline_avg_7d=input_data.get("baseline_avg_7d", "n/a"),
        baseline_ratio=input_data.get("baseline_ratio", "n/a"),
        anomaly_flag=input_data.get("anomaly_flag", False),
        action=action,
        specific_action=action,
    )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    # Sequential routing: DeepSeek → OpenAI → Grok with detailed failure logging
    logger.info("[Advisor] Starting LLM routing for advisory generation...")
    text, model_used = route_llm(messages, temperature=TEMPERATURE, usage_counts=_model_usage_counts)

    if not text:
        # Enhanced logging for debugging LLM failures
        logger.error("[Advisor] CRITICAL: All LLM providers failed to generate advisory")
        logger.error(f"[Advisor] Final usage counts: {_model_usage_counts}")
        logger.error(f"[Advisor] Alert context: category={alert.get('category')}, region={alert.get('region')}, score={alert.get('score')}")
        logger.error(f"[Advisor] User message length: {len(user_message)} chars")
        logger.error(f"[Advisor] System prompt length: {len(system_content)} chars")
        logger.error("[Advisor] Falling back to deterministic template...")
        
        # Track fallback usage
        _model_usage_counts["fallback"] = _model_usage_counts.get("fallback", 0) + 1
        
        return _fallback_advisory(alert, trend_line, input_data, geographic_warning)

    logger.info(f"[Advisor] Successfully generated advisory using {model_used}")
    logger.info(f"[Advisor] Current usage counts: {_model_usage_counts}")
    advisory = text

    if trend_line not in advisory:
        advisory += ("\n\n" + trend_line)

    # Add ALTERNATIVES if applicable
    alts = input_data.get("alternatives") or []
    if alts and "ALTERNATIVES —" not in advisory:
        advisory += "\n\nALTERNATIVES —\n" + "\n".join(f"• {a}" for a in alts)

    # Role blocks - Only add if section is missing AND no role-specific content exists
    role_blocks = input_data.get("role_actions") or {}
    if role_blocks and "ROLE-SPECIFIC ACTIONS —" not in advisory:
        # Check if role-specific content already exists inline (to prevent duplication)
        has_inline_roles = False
        role_patterns = [r.replace("_", " ").title() for r in role_blocks.keys()]
        for pattern in role_patterns:
            if f"[{pattern}]" in advisory:
                has_inline_roles = True
                break
        
        # Only add role section if no inline role content exists
        if not has_inline_roles:
            advisory += "\n\nROLE-SPECIFIC ACTIONS —"
            for role, items in role_blocks.items():
                title = role.replace("_"," ").title()
                for it in items:
                    advisory += f"\n• [{title}] {it}"

    # Source reliability section (proactive skepticism)
    src_lines = _sources_reliability_lines(input_data.get("sources") or [])
    if src_lines and "SOURCES —" in advisory and "SOURCE RELIABILITY —" not in advisory:
        advisory += "\n\nSOURCE RELIABILITY —\n" + "\n".join(src_lines)

    # Info-ops flags visibility
    if input_data.get("info_ops_flags") and "SOURCES —" in advisory and "INFO-OPS / SIGNALS —" not in advisory:
        advisory += "\n\nINFO-OPS / SIGNALS —\n" + "\n".join(f"- {f}" for f in input_data["info_ops_flags"])

    # Geographic validation warning - add prominent warning for location mismatches
    if geographic_warning and "GEOGRAPHIC VALIDATION —" not in advisory:
        advisory += f"\n\nGEOGRAPHIC VALIDATION —\n⚠️ {geographic_warning}"

    # Add data provenance section showing location/quality warnings
    advisory = _add_data_provenance_section(advisory, input_data)
    
    advisory = ensure_sections(advisory)
    advisory = ensure_has_playbook_or_alts(advisory, hits, alts)
    advisory = clean_auto_sections(advisory)
    advisory = trim_verbose_explanation(advisory)
    advisory = strip_excessive_blank_lines(advisory)
    return advisory

def _fallback_advisory(alert: Dict[str, Any], trend_line: str, input_data: Dict[str, Any], geographic_warning: str = "") -> str:
    region = input_data.get("region") or "Unknown location"
    risk_level = alert.get("label") or "Unknown"
    threat_type = input_data.get("category") or "Other"
    
    # FIXED: Convert Decimal confidence to float
    confidence_val = alert.get("confidence", 0.7)
    if isinstance(confidence_val, decimal.Decimal):
        confidence_val = float(confidence_val)
    
    # NEW: Apply confidence floor based on location/data quality
    location_score = input_data.get("location_match_score", 0)
    is_valid = input_data.get("data_statistically_valid", False)
    
    confidence_val = float(confidence_val)
    
    if location_score < 30:
        confidence_val = min(confidence_val, 0.15)  # Cap at 15% for severe mismatch
    if not is_valid:
        confidence_val = min(confidence_val, 0.25)  # Cap at 25% for low data
    
    confidence = int(round(100 * confidence_val))
    
    sources = ", ".join([s.get("name","Source") for s in input_data.get("sources") or []]) or "Multiple"
    domains = input_data.get("domains") or []
    hits = input_data.get("domain_playbook_hits") or {}
    alts = input_data.get("alternatives") or []
    ewi = input_data.get("early_warning_indicators") or []
    role_blocks = input_data.get("role_actions") or {}
    next_review = input_data.get("next_review_hours", "12h")

    lines = []
    lines.append(f"ALERT — {region} | {risk_level} | {threat_type}")
    lines.append("BULLETPOINT RISK SUMMARY —")
    # Safe decimal conversion for baseline_ratio
    baseline_ratio = alert.get('baseline_ratio', 1.0)
    if hasattr(baseline_ratio, 'to_eng_string'):  # Decimal case
        baseline_ratio = float(baseline_ratio)
    
    lines.append(f"- Trend: {alert.get('trend_direction','stable')} | 7d/baseline: {baseline_ratio}x | 30d: {alert.get('incident_count_30d','n/a')}")
    if alert.get("anomaly_flag", alert.get("is_anomaly")): lines.append("- Anomaly: true (pattern deviation)")
    lines.append("TRIGGERS / KEYWORDS — (see sources)")
    lines.append(f"CATEGORIES / SUBCATEGORIES — {threat_type} / {alert.get('subcategory','Unspecified')}")
    lines.append(f"SOURCES — {sources}")
    lines.append(f"REPORTS ANALYZED — {input_data.get('reports_analyzed',1)}")
    lines.append(f"CONFIDENCE — {confidence}")

    lines.append("WHAT TO DO NOW —")
    if "travel_mobility" in domains:
        lines.append("• Adjust departures ±15–30 min; use secondary arterials; avoid choke points/checkpoints.")
    if "physical_safety" in domains:
        lines.append("• Avoid poorly lit choke points after 20:00; stage near 24/7 venues; buddy-up on foot.")
    if {"cyber_it","digital_privacy_surveillance"} & set(domains):
        lines.append("• Enforce passkeys/MFA; disable auto-join Wi-Fi/Bluetooth; use a vetted VPN; avoid untrusted Wi-Fi.")

    lines.append("HOW TO PREPARE —")
    if "travel_mobility" in domains:
        lines.append("• Pre-map two alternates; confirm curfew windows; keep fuel ≥1/2 tank.")
    if "physical_safety" in domains:
        lines.append("• Identify two safe havens within 200 m; set a check-in protocol; use low-profile clothing.")
    if {"cyber_it","digital_privacy_surveillance"} & set(domains):
        lines.append("• Enforce passkeys, password manager; geo-fence admin; travel with a clean device.")

    lines.append("ROLE-SPECIFIC ACTIONS —")
    for role, items in role_blocks.items():
        title = role.replace("_"," ").title()
        for it in items:
            lines.append(f"• [{title}] {it}")

    lines.append("DOMAIN PLAYBOOK HITS —")
    if hits:
        for k, v in hits.items():
            for tip in v:
                lines.append(f"• [{k}] {tip}")
    else:
        lines.append("• No additional playbook tips available.")

    if alts:
        lines.append("ALTERNATIVES —")
        for a in alts:
            lines.append(f"• {a}")

    lines.append("FORECAST —")
    lines.append(f"• Direction: {alert.get('trend_direction','stable')} | Next review: {next_review} | Early warnings: {', '.join(ewi) if ewi else 'none'}")

    # Replace verbose EXPLANATION with concise version (max 2 lines)
    explanation_lines = [
        f"• {trend_line[:150]}...",  # Truncate to prevent rambling
        "• Confidence adjusted for location precision and source reliability."
    ]
    # Note: Any warnings about location/data are presented in dedicated sections
    # (GEOGRAPHIC VALIDATION — / DATA PROVENANCE —) to keep EXPLANATION concise.
    
    lines.append("EXPLANATION —")
    lines.extend(explanation_lines)

    lines.append("ANALYST CTA —")
    lines.append("• Reply 'monitor 12h' for an auto-check, or request a routed analyst review if risk increases.")

    # Add geographic validation warning if present
    if geographic_warning:
        lines.append("GEOGRAPHIC VALIDATION —")
        lines.append(f"⚠️ {geographic_warning}")

    out = "\n".join(lines)
    out = ensure_sections(out)
    out = ensure_has_playbook_or_alts(out, hits, alts)
    out = clean_auto_sections(out)
    out = strip_excessive_blank_lines(out)
    return out

# ---------- Public wrappers ----------
def generate_advice(query, alerts, user_profile=None, **kwargs):
    """
    Generates advice based on the query and alert list.
    - NEW: if multiple alerts provided, merge top-3 by score for a single, coherent advisory.
    - Soft relevance guard: drops clear sports-only items when mixed in bulk.
    Returns {"reply": advisory, "alerts": alerts, "meta": {...}} to support proactive follow-ups.
    """
    if not alerts:
        alert = {}
    else:
        # Filter obvious sports-only noise (non-breaking; retains primary if only one)
        if len(alerts) > 1:
            alerts = [a for a in alerts if not _is_soft_irrelevant(a)] or alerts
        alert = _aggregate_alerts(alerts)

    advisory = render_advisory(alert, query, user_profile)

    meta = {
        "next_review": (_monitoring_cadence(
            alert.get("trend_direction","stable"),
            bool(alert.get("anomaly_flag", alert.get("is_anomaly"))),
            _infer_roles(user_profile, query),
            alert.get("future_risk_probability"))
        ) if alert else "12h",
        "future_risk_probability": alert.get("future_risk_probability") if alert else None,
        "trend_direction": alert.get("trend_direction") if alert else None,
        "domains": alert.get("domains") if alert else [],
    }

    return {"reply": advisory, "alerts": alerts, "meta": meta}

def handle_user_query(payload: dict, email: str = "", **kwargs) -> dict:
    """
    Compatibility wrapper so callers expecting advisor.handle_user_query() still work.
    payload: { query, profile_data, input_data }
    Returns a dict with at least { reply }.
    """
    query = (payload.get("query") or "").strip()
    profile = payload.get("profile_data") or {}
    alerts = (payload.get("input_data") or {}).get("alerts") or []
    
    try:
        result = generate_advice(query, alerts, user_profile=profile, **kwargs)  # type: ignore
        if isinstance(result, str):
            return {"reply": result, "alerts": alerts}
        if isinstance(result, dict) and "reply" in result:
            return result
        return {"reply": json.dumps(result, ensure_ascii=False, default=_json_serialize), "alerts": alerts}
    except Exception as e:
        logger.error(f"[Advisor] handle_user_query failed: {e}")
        logger.error(f"[Advisor] Query: {query[:100]}...")
        logger.error(f"[Advisor] Alerts count: {len(alerts)}")
        logger.error(f"[Advisor] Final fallback to render_advisory...")
        
        # Track this as an additional fallback
        _model_usage_counts["handle_query_fallback"] = _model_usage_counts.get("handle_query_fallback", 0) + 1
        
        alert = alerts[0] if alerts else {}
        advisory = render_advisory(alert, query, profile)
        return {"reply": advisory, "alerts": alerts}