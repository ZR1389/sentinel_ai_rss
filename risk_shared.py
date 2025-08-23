# risk_shared.py — Shared enrichment & analytics (canonical detectors + helpers) • v2025-08-22+patch1
# Used by: RSS Processor, Threat Engine, Scorer, Advisor. No metered LLM calls here.

from __future__ import annotations
import re
import math
from typing import Dict, List, Tuple, Optional

try:
    from unidecode import unidecode
except Exception:
    def unidecode(s: str) -> str:  # no-op fallback
        return s

# ---------------------- Canonical taxonomies ----------------------
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "Crime": ["robbery","assault","shooting","stabbing","murder","burglary","theft","carjacking","homicide","looting"],
    "Terrorism": ["ied","vbied","suicide bomber","terrorist","bomb","explosion","martyrdom"],
    "Civil Unrest": ["protest","riot","demonstration","march","sit-in","clash","looting","roadblock","strike"],
    "Cyber": ["ransomware","phishing","malware","breach","ddos","credential","data leak","zero-day","cve","exploit","backdoor"],
    "Infrastructure": ["substation","pipeline","power outage","grid","transformer","telecom","fiber","water plant","facility","sabotage","blackout"],
    "Environmental": ["earthquake","flood","hurricane","storm","wildfire","heatwave","landslide","mudslide","tornado","cyclone"],
    "Epidemic": ["epidemic","pandemic","outbreak","cholera","dengue","covid","ebola","avian flu"],
    "Other": []
}

SUBCATEGORY_MAP: Dict[str, Dict[str, str]] = {
    "Crime": {
        "robbery":"Armed Robbery","assault":"Aggravated Assault","shooting":"Targeted Shooting",
        "stabbing":"Knife Attack","burglary":"Burglary","carjacking":"Carjacking","looting":"Looting",
    },
    "Terrorism": {
        "ied":"IED Attack","vbied":"VBIED","suicide bomber":"Suicide Attack","bomb":"Bombing","explosion":"Bombing",
    },
    "Civil Unrest": {
        "protest":"Protest","riot":"Riot","looting":"Looting","strike":"Strike/Industrial Action",
        "roadblock":"Road Blockade","clash":"Police–Protester Clash",
    },
    "Cyber": {
        "ransomware":"Ransomware","phishing":"Phishing","breach":"Data Breach","ddos":"DDoS",
        "credential":"Account Takeover","zero-day":"Zero-Day Exploit","cve":"Vulnerability Exploitation",
    },
    "Infrastructure": {
        "pipeline":"Pipeline Incident","substation":"Substation Sabotage","grid":"Grid Disruption",
        "power outage":"Power Outage","telecom":"Telecom Outage","water plant":"Water Utility Incident",
        "facility":"Facility Incident","blackout":"Power Outage",
    },
    "Environmental": {
        "flood":"Flooding","hurricane":"Hurricane/Typhoon","earthquake":"Earthquake",
        "wildfire":"Wildfire","storm":"Severe Storm","landslide":"Landslide","heatwave":"Heatwave",
    },
    "Epidemic": {
        "cholera":"Cholera","dengue":"Dengue","covid":"COVID-19","ebola":"Ebola","avian flu":"Avian Influenza","outbreak":"Disease Outbreak",
    },
}

DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "travel_mobility": ["travel","route","road","highway","checkpoint","curfew","airport","border","port","rail","metro","detour","closure","traffic","mobility"],
    "cyber_it": ["cyber","hacker","phishing","ransomware","malware","data breach","ddos","credential","mfa","passkey","vpn","exploit","zero-day","cve","edr"],
    "digital_privacy_surveillance": ["surveillance","counter-surveillance","device check","imsi","stingray","tracking","tail","biometric","unlock","spyware","pegasus","finfisher","watchlist"],
    "physical_safety": ["kidnap","abduction","theft","assault","shooting","stabbing","robbery","looting","attack","murder"],
    "civil_unrest": ["protest","riot","demonstration","clash","strike","roadblock"],
    "kfr_extortion": ["kidnap","kidnapping","kfr","ransom","extortion"],
    "infrastructure_utilities": ["infrastructure","power","grid","substation","pipeline","telecom","fiber","facility","sabotage","water","blackout"],
    "environmental_hazards": ["earthquake","flood","hurricane","storm","wildfire","heatwave","landslide","mudslide"],
    "public_health_epidemic": ["epidemic","pandemic","outbreak","cholera","dengue","covid","ebola","avian flu"],
    "ot_ics": ["scada","ics","plc","ot","industrial control","hmi"],
    "info_ops_disinfo": ["misinformation","disinformation","propaganda","info ops","psyop"],
    "legal_regulatory": ["visa","immigration","border control","curfew","checkpoint order","permit","license","ban","restriction"],
    "business_continuity_supply": ["supply chain","logistics","port congestion","warehouse","shortage","inventory"],
    "insider_threat": ["insider","employee","privileged access","badge","tailgating"],
    "residential_premises": ["residential","home invasion","burglary","apartment","compound"],
    "emergency_medical": ["casualty","injured","fatalities","triage","medical","ambulance"],
    "counter_surveillance": ["surveillance","tail","followed","sdr","sd r","surveillance detection"],  # added both 'sdr' and 'sd r'
    "terrorism": ["ied","vbied","suicide bomber","terrorist","bomb"]
}

# ---------------------- Text normalization ----------------------
def _normalize(text: str) -> str:
    """
    Normalize text once for all checks:
      - lowercase
      - strip accents (unidecode)
      - treat hyphens/emdashes as spaces so 'zero-day' == 'zero day'
      - collapse whitespace
    """
    if not text:
        return ""
    t = unidecode(text).lower()
    t = re.sub(r"[-–—]+", " ", t)   # <-- patch: hyphen/emdash normalization
    t = re.sub(r"\s+", " ", t)
    return t.strip()

# ---------------------- Utilities ----------------------
def _count_hits(text: str, keywords: List[str]) -> int:
    t = _normalize(text)
    return sum(1 for k in keywords if k in t)

# Expose a flattened, deduped keyword list (useful for RSS processor)
def get_all_keywords() -> List[str]:
    seen = set()
    out: List[str] = []
    for lst in list(CATEGORY_KEYWORDS.values()) + list(DOMAIN_KEYWORDS.values()):
        for k in lst:
            kk = _normalize(k)
            if kk and kk not in seen:
                seen.add(kk)
                out.append(kk)
    return out

KEYWORD_SET = set(get_all_keywords())

# ---------------------- Existing public API (kept) ----------------------
def compute_keyword_weight(text: str) -> float:
    """Simple salience estimator 0..1 based on combined domain/category hits."""
    if not text:
        return 0.0
    total = 0
    for klist in list(CATEGORY_KEYWORDS.values()) + list(DOMAIN_KEYWORDS.values()):
        total += _count_hits(text, klist)
    return min(1.0, 1 - math.exp(-0.3 * total))

def enrich_log(text: str) -> str:
    w = compute_keyword_weight(text)
    return f"kw_weight={w:.2f}"

def enrich_log_db(text: str) -> str:
    return enrich_log(text)

def run_sentiment_analysis(text: str) -> str:
    t = _normalize(text)
    neg = ["killed","dead","fatal","attack","explosion","panic","riot","fear","threat","warning","evacuate","emergency"]
    pos = ["contained","stabilized","safe","secured","reopened","de-escalate","calm"]
    score = _count_hits(t, neg) - _count_hits(t, pos)
    if score >= 3: return "High concern"
    if score == 2: return "Elevated"
    if score == 1: return "Notice"
    return "Neutral/Informational"

def run_forecast(text: str, location: Optional[str] = None) -> str:
    """
    Lightweight rule-based forecast. Signature accepts optional `location`
    to match threat_engine usage; ignored if None.
    """
    t = _normalize(text)
    if any(k in t for k in ["protest","riot","unrest","clash"]):
        base = "Short-term risk of renewed protests remains; expect pop-up roadblocks and police activity."
        return f"{base} ({location})" if location else base
    if any(k in t for k in ["ransomware","breach","phishing","malware"]):
        base = "Cyber threat remains elevated; harden MFA/passkeys and monitor admin anomalies."
        return f"{base} ({location})" if location else base
    if any(k in t for k in ["flood","storm","wildfire","hurricane"]):
        base = "Weather-related disruption likely; plan daylight moves and check closures hourly."
        return f"{base} ({location})" if location else base
    return "No clear short-term escalation signal from content alone."

def run_legal_risk(text: str, region: Optional[str] = None) -> str:
    t = _normalize(text)
    if "curfew" in t or "checkpoint" in t:
        return "Verify curfew windows and checkpoint orders; carry ID/permits where applicable."
    if "visa" in t or "immigration" in t or "border" in t:
        return "Confirm current visa/entry rules and device search policies; minimize device data at ports."
    return "No immediate legal or regulatory constraints identified."

def run_cyber_ot_risk(text: str) -> str:
    t = _normalize(text)
    if any(k in t for k in ["ransomware","malware","breach","data","ddos","phishing","credential","cve","zero-day","exploit"]):
        return "Prioritize passkeys/MFA, patching of exposed services, and geo-fencing of admin access."
    if any(k in t for k in ["scada","ics","ot","plc","hmi"]):
        return "Segment OT networks, disable unsolicited remote access, and enforce break-glass accounts."
    return "No priority cyber/OT actions from the text alone."

def run_environmental_epidemic_risk(text: str) -> str:
    t = _normalize(text)
    if any(k in t for k in ["flood","wildfire","hurricane","storm","heatwave","earthquake","landslide"]):
        return "Prepare for environmental disruptions: closures, air quality, and power issues."
    if any(k in t for k in ["epidemic","pandemic","cholera","dengue","covid","ebola","avian flu","outbreak"]):
        return "Maintain hygiene protocols and review medical access; consider masks and bottled water."
    return "No immediate environmental or epidemic flags."

def extract_threat_category(text: str) -> Tuple[str, float]:
    t = _normalize(text)
    best_cat, best_hits = "Other", 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        hits = _count_hits(t, kws)
        if hits > best_hits:
            best_hits, best_cat = hits, cat
    conf = min(1.0, 0.25 + 0.15 * best_hits)
    return best_cat, conf

def extract_threat_subcategory(text: str, category: str) -> str:
    t = _normalize(text)
    mapping = SUBCATEGORY_MAP.get(category, {})
    for k, sub in mapping.items():
        if k in t:
            return sub
    return "Unspecified"

# ---------------------- NEW: canonical detectors & helpers ----------------------
def detect_domains(text: str) -> List[str]:
    """Detect all relevant domains from content (stable order)."""
    if not text: return []
    t = _normalize(text)
    hits = []
    for dom, kws in DOMAIN_KEYWORDS.items():
        if any(k in t for k in kws):
            hits.append(dom)
    # category-driven augmentation
    cat, _ = extract_threat_category(text)
    if cat == "Civil Unrest":
        for d in ["civil_unrest","physical_safety","travel_mobility"]:
            if d not in hits: hits.append(d)
    elif cat == "Terrorism":
        for d in ["terrorism","physical_safety"]:
            if d not in hits: hits.append(d)
    elif cat == "Environmental":
        for d in ["environmental_hazards","emergency_medical"]:
            if d not in hits: hits.append(d)
    elif cat == "Epidemic":
        for d in ["public_health_epidemic","emergency_medical"]:
            if d not in hits: hits.append(d)
    order = list(DOMAIN_KEYWORDS.keys())
    return sorted(set(hits), key=lambda d: order.index(d) if d in order else 999)

_TRUSTED_HOSTS = {
    "reuters.com","apnews.com","bbc.co.uk","bbc.com","nytimes.com","osac.gov","who.int",
    "emsc-csem.org","cdc.gov","ecdc.europa.eu","france24.com","aljazeera.com","scmp.com"
}
def source_reliability(source_name: Optional[str], source_url: Optional[str]) -> Tuple[str, str]:
    """Returns (rating, reason)."""
    s = (source_name or "").lower()
    host = ""
    try:
        from urllib.parse import urlparse
        host = urlparse(source_url or "").netloc.lower()
    except Exception:
        pass

    # <-- patch: handle composite government domains like gov.uk, gov.br, etc.
    parts = host.split(".") if host else []
    if ("gov" in parts) or ("mil" in parts) or (parts[-1:] and parts[-1] in {"eu", "int"}):
        return "High", "Official government/institutional source"

    if any(h in host for h in _TRUSTED_HOSTS):
        return "High", "Reputable international outlet"
    if any(k in host for k in ["twitter.com","x.com","t.me","telegram","facebook.com","medium.com","substack.com"]):
        return "Moderate", "Social/blog channel—verify with a second source"
    if not host and any(k in s for k in ["police","ministry","embassy","consulate"]):
        return "Moderate", "Official-sounding name—verify URL"
    return "Unknown", "Unable to verify source reputation"

_INFOOPS_PATTERNS = [
    r"\bbreaking\b", r"\bshocking\b", r"\bshare this\b", r"!!!", r"!!!!",
    r"\bsecret plan\b", r"\binside sources\b"
]
def info_ops_flags(text: str) -> List[str]:
    if not text: return []
    t = _normalize(text)
    flags = []
    for pat in _INFOOPS_PATTERNS:
        if re.search(pat, t):
            flags.append(pat.strip("\\b"))
    if _count_hits(t, ["share","forward","viral"]) >= 2:
        flags.append("viral-amplification")
    return flags

def baseline_from_counts(recent_7d: int, past_56d_total: int) -> Tuple[float, float, str]:
    """Returns (baseline_avg_7d, ratio, trend_direction)."""
    base_avg = float(past_56d_total) / 8.0 if past_56d_total else 0.0
    ratio = (recent_7d / base_avg) if base_avg > 0 else (1.0 if recent_7d > 0 else 0.0)
    if   ratio > 1.25: trend = "increasing"
    elif ratio < 0.80: trend = "decreasing"
    else:              trend = "stable"
    return round(base_avg,3), round(ratio,3), trend

def ewma_anomaly(counts: List[int], alpha: float = 0.4, k: float = 2.5) -> bool:
    """EWMA thresholding: mark anomaly if today > mu + k*sigma."""
    if not counts:
        return False
    mu = float(counts[0])
    var = 0.0
    for x in counts[1:]:
        mu = alpha*float(x) + (1-alpha)*mu
        var = alpha*(float(x)-mu)**2 + (1-alpha)*var
    sigma = math.sqrt(var)
    return float(counts[-1]) > (mu + (k*sigma if sigma > 0 else 3.0))

def extract_location(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Wrapper around city_utils; returns (city, country). Never raises."""
    try:
        from city_utils import fuzzy_match_city, normalize_city
        c = fuzzy_match_city(text or "")
        if c:
            city, country = normalize_city(c)
            return city, country
    except Exception:
        pass
    return None, None
