# risk_shared.py — Shared enrichment & analytics (canonical detectors + helpers) • v2025-08-22+patch3 (2025-08-31)
# Used by: RSS Processor, Threat Engine, Scorer, Advisor. No metered LLM calls here.

from __future__ import annotations
import re
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Sequence

try:
    from unidecode import unidecode
except Exception:
    def unidecode(s: str) -> str:  # no-op fallback
        return s

# ---------------------- Canonical taxonomies ----------------------
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "Crime": [
        "robbery","assault","shooting","stabbing","murder","burglary","theft","carjacking","homicide","looting",
        # add a few common crime verbs/nouns
        "kidnap","kidnapping","abduction","arson","home invasion"
    ],
    "Terrorism": [
        "ied","vbied","suicide bomber","terrorist","bomb","explosion","martyrdom",
        # expanded kinetic/munitions
        "blast","grenade","improvised explosive","car bomb","truck bomb","shelling","mortar","drone strike","airstrike","air strike","artillery"
    ],
    "Civil Unrest": [
        "protest","riot","demonstration","march","sit-in","clash","looting","roadblock","strike"
    ],
    "Cyber": [
        "ransomware","phishing","malware","breach","ddos","credential","data leak","data leakage",
        "zero-day","zero day","cve","exploit","backdoor","credential stuffing","wiper","data breach"
    ],
    "Infrastructure": [
        "substation","pipeline","power outage","grid","transformer","telecom","fiber","water plant","facility","sabotage","blackout",
        "subsea cable","dam","bridge","transformer fire"
    ],
    "Environmental": [
        "earthquake","flood","hurricane","storm","wildfire","heatwave","landslide","mudslide","tornado","cyclone"
    ],
    "Epidemic": [
        "epidemic","pandemic","outbreak","cholera","dengue","covid","ebola","avian flu"
    ],
    "Other": []
}

SUBCATEGORY_MAP: Dict[str, Dict[str, str]] = {
    "Crime": {
        "robbery":"Armed Robbery","assault":"Aggravated Assault","shooting":"Targeted Shooting",
        "stabbing":"Knife Attack","burglary":"Burglary","carjacking":"Carjacking","looting":"Looting",
        "kidnap":"Kidnap","kidnapping":"Kidnap"
    },
    "Terrorism": {
        "ied":"IED Attack","vbied":"VBIED","suicide bomber":"Suicide Attack","bomb":"Bombing","explosion":"Bombing",
        "grenade":"Grenade Attack","drone strike":"Drone Strike","airstrike":"Airstrike","air strike":"Airstrike"
    },
    "Civil Unrest": {
        "protest":"Protest","riot":"Riot","looting":"Looting","strike":"Strike/Industrial Action",
        "roadblock":"Road Blockade","clash":"Police–Protester Clash"
    },
    "Cyber": {
        "ransomware":"Ransomware","phishing":"Phishing","breach":"Data Breach","ddos":"DDoS",
        "credential":"Account Takeover","zero-day":"Zero-Day Exploit","zero day":"Zero-Day Exploit",
        "cve":"Vulnerability Exploitation","credential stuffing":"Credential Stuffing","wiper":"Wiper Malware",
        "data leak":"Data Leak","data leakage":"Data Leak"
    },
    "Infrastructure": {
        "pipeline":"Pipeline Incident","substation":"Substation Sabotage","grid":"Grid Disruption",
        "power outage":"Power Outage","telecom":"Telecom Outage","water plant":"Water Utility Incident",
        "facility":"Facility Incident","blackout":"Power Outage","subsea cable":"Subsea Cable Disruption",
        "dam":"Dam Incident","bridge":"Bridge Closure/Incident","transformer":"Transformer Incident"
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
    "travel_mobility": ["travel","route","road","highway","checkpoint","curfew","airport","border","port","rail","metro","detour","closure","traffic","mobility","bridge","service suspended"],
    "cyber_it": ["cyber","hacker","phishing","ransomware","malware","data breach","ddos","credential","mfa","passkey","vpn","exploit","zero-day","zero day","cve","edr","credential stuffing","wiper"],
    "digital_privacy_surveillance": ["surveillance","counter-surveillance","device check","imsi","stingray","tracking","tail","biometric","unlock","spyware","pegasus","finfisher","watchlist"],
    "physical_safety": ["kidnap","abduction","theft","assault","shooting","stabbing","robbery","looting","attack","murder","grenade","arson"],
    "civil_unrest": ["protest","riot","demonstration","clash","strike","roadblock","sit-in","march"],
    "kfr_extortion": ["kidnap","kidnapping","kfr","ransom","extortion","hostage"],
    "infrastructure_utilities": ["infrastructure","power","grid","substation","pipeline","telecom","fiber","facility","sabotage","water","blackout","subsea cable","transformer","dam"],
    "environmental_hazards": ["earthquake","flood","hurricane","storm","wildfire","heatwave","landslide","mudslide","tornado","cyclone"],
    "public_health_epidemic": ["epidemic","pandemic","outbreak","cholera","dengue","covid","ebola","avian flu"],
    "ot_ics": ["scada","ics","plc","ot","industrial control","hmi"],
    "info_ops_disinfo": ["misinformation","disinformation","propaganda","info ops","psyop"],
    "legal_regulatory": ["visa","immigration","border control","curfew","checkpoint order","permit","license","ban","restriction"],
    "business_continuity_supply": ["supply chain","logistics","port congestion","warehouse","shortage","inventory"],
    "insider_threat": ["insider","employee","privileged access","badge","tailgating"],
    "residential_premises": ["residential","home invasion","burglary","apartment","compound"],
    "emergency_medical": ["casualty","injured","fatalities","triage","medical","ambulance"],
    "counter_surveillance": ["surveillance","tail","followed","sdr","sd r","surveillance detection"],
    "terrorism": ["ied","vbied","suicide bomber","terrorist","bomb","explosion","drone strike","airstrike","air strike","grenade","blast","mortar","artillery"]
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
    t = re.sub(r"[-–—]+", " ", t)   # hyphen/emdash normalization
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
    neg = ["killed","dead","fatal","attack","explosion","panic","riot","fear","threat","warning","evacuate","emergency","hostage"]
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
    if any(k in t for k in ["ransomware","malware","breach","data","ddos","phishing","credential","cve","zero-day","zero day","exploit","credential stuffing","wiper"]):
        return "Prioritize passkeys/MFA, patching of exposed services, and geo-fencing of admin access."
    if any(k in t for k in ["scada","ics","ot","plc","hmi"]):
        return "Segment OT networks, disable unsolicited remote access, and enforce break-glass accounts."
    return "No priority cyber/OT actions from the text alone."

def run_environmental_epidemic_risk(text: str) -> str:
    t = _normalize(text)
    if any(k in t for k in ["flood","wildfire","hurricane","storm","heatwave","earthquake","landslide","tornado","cyclone","mudslide"]):
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

# ---------------------- Canonical detectors & helpers ----------------------
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

    # handle composite government domains like gov.uk, gov.br, etc.
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

# ---------------------- Optional: false-positive guards (non-breaking) ----------------------
# These helpers are intentionally conservative and only fire when *clearly* in a sports context
# and no security keywords are present. Use from Threat Engine relevance gate if desired.

_SPORTS_TOKENS = [
    "game","match","season","league","tournament","playoff","finals","championship",
    "coach","manager","quarterback","striker","midfielder","defender","goalkeeper","pitcher","shortstop",
    "score","scored","goal","assist","points","win","loss","draw","fixture",
    "nba","nfl","mlb","nhl","uefa","fifa","premier league","la liga","bundesliga","serie a",
    "offense","offence","defense","defence","lineup","roster","draft","trade","transfer",
]

def likely_sports_context(text: str) -> bool:
    """
    Heuristic: return True if multiple sports tokens present AND no security tokens present.
    Does not mutate any existing behavior; can be used by a relevance gate upstream.
    """
    t = _normalize(text or "")
    if not t:
        return False
    sports_hits = sum(1 for k in _SPORTS_TOKENS if k in t)
    if sports_hits < 2:
        return False
    # any overlap with our security keywords? if yes, don't flag
    if any(k in t for k in KEYWORD_SET):
        return False
    return True

def relevance_flags(text: str) -> List[str]:
    """
    Returns light flags you can log or use upstream:
      - 'sports_context' if likely sports content
      - 'info_ops' if sensational patterns present
    """
    flags: List[str] = []
    if likely_sports_context(text):
        flags.append("sports_context")
    if info_ops_flags(text):
        flags.append("info_ops")
    return flags

# =====================================================================
#                KEYWORD / CO-OCCURRENCE MATCHER (NEW)
# =====================================================================

# Broad terms only matter when paired with an impact word/phrase (below).
BROAD_TERMS_DEFAULT: List[str] = [
    "travel advisory", "security alert", "embassy alert",
    "state of emergency", "martial law", "curfew", "lockdown",
    "heightened security", "evacuation order", "shelter in place",
    "airport closure", "border closure", "flight cancellation", "flight cancellations",
    "airspace closed", "no-fly zone", "ground stop", "notam",
    "strike", "walkout", "industrial action", "work stoppage",
    "internet shutdown", "telecom outage", "nationwide outage",
    "power blackout", "blackout",
]

# Impact terms represent real-world consequences or violence.
IMPACT_TERMS_DEFAULT: List[str] = [
    "killed", "dead", "fatalities", "fatality",
    "injured", "wounded", "shot", "stabbed", "burned",
    "looted", "arson", "clashes", "barricades",
    "arrested", "detained", "deported",
    "closed", "suspended", "cancelled", "canceled", "disrupted", "delayed", "blocked",
    "evacuated", "evacuation", "trapped", "missing",
    "curfew", "martial law", "state of emergency",
]

# Tokenizer & sentence-split (operate on normalized text)
_WORD = re.compile(r"\b[\w]+\b", re.UNICODE)
_SENT_SPLIT = re.compile(r"(?<=[\.\!\?\u2026])\s+|\n+")

def _tokenize(text: str) -> List[str]:
    return _WORD.findall(_normalize(text))

def _sentences(text: str) -> List[str]:
    nt = _normalize(text)
    return [s.strip() for s in _SENT_SPLIT.split(nt) if s.strip()]

def _compile_phrase_regex(phrases: Sequence[str]) -> re.Pattern:
    """
    Compile phrases against *normalized* text.
    Example: 'no-fly zone' becomes tokens ['no','fly','zone'] and matches with flexible whitespace.
    """
    parts: List[str] = []
    for p in phrases:
        p = _normalize(p)
        if not p:
            continue
        toks = [re.escape(tok) for tok in p.split()]
        parts.append(r"\b" + r"\s+".join(toks) + r"\b")
    if not parts:
        return re.compile(r"^\a$")  # never matches
    return re.compile("|".join(parts), re.IGNORECASE)

def _phrase_token_positions(tokens: List[str], phrases: Sequence[str]) -> List[int]:
    """Return starting token indices where a phrase (as tokens) occurs."""
    positions: List[int] = []
    ph_tokens = [tuple(_normalize(p).split()) for p in phrases if _normalize(p)]
    n = len(tokens)
    for i in range(n):
        for ph in ph_tokens:
            L = len(ph)
            if L and i + L <= n and tuple(tokens[i:i+L]) == ph:
                positions.append(i)
    return positions

@dataclass
class MatchResult:
    hit: bool
    rule: Optional[str]
    matches: Dict[str, List[str]]

class KeywordMatcher:
    """
    Rules:
      1) If any strict keyword appears anywhere               -> HIT ("keyword")
      2) Else, if any sentence has >=1 broad AND >=1 impact  -> HIT ("broad+impact(sent)")
      3) Else, if any broad within 'window' tokens of impact -> HIT ("broad+impact(window)")
      4) Else -> no hit
    """
    def __init__(self,
                 keywords: Sequence[str],
                 broad_terms: Sequence[str] = BROAD_TERMS_DEFAULT,
                 impact_terms: Sequence[str] = IMPACT_TERMS_DEFAULT,
                 window: int = 12):
        self.keywords_list = list(dict.fromkeys([_normalize(x) for x in keywords if _normalize(x)]))
        self.broad_list    = list(dict.fromkeys([_normalize(x) for x in broad_terms if _normalize(x)]))
        self.impact_list   = list(dict.fromkeys([_normalize(x) for x in impact_terms if _normalize(x)]))
        self.window        = max(1, int(window))
        self._kw_re        = _compile_phrase_regex(self.keywords_list)
        self._broad_re     = _compile_phrase_regex(self.broad_list)
        self._impact_re    = _compile_phrase_regex(self.impact_list)

    def decide(self, text: str, title: str = "") -> MatchResult:
        full = f"{title or ''} {text or ''}"

        # Rule 1: strict keywords anywhere
        nt = _normalize(full)
        kw_hits = sorted(set(m.group(0).lower() for m in self._kw_re.finditer(nt)))
        if kw_hits:
            return MatchResult(True, "keyword", {"keywords": kw_hits})

        # Rule 2: sentence-level co-occurrence
        for sent in _sentences(full):
            b = sorted(set(m.group(0).lower() for m in self._broad_re.finditer(sent)))
            if not b:
                continue
            i = sorted(set(m.group(0).lower() for m in self._impact_re.finditer(sent)))
            if b and i:
                return MatchResult(True, "broad+impact(sent)", {"broad": b, "impact": i})

        # Rule 3: token-window co-occurrence
        toks = _tokenize(full)
        if toks:
            bpos = _phrase_token_positions(toks, self.broad_list)
            ipos = _phrase_token_positions(toks, self.impact_list)
            if bpos and ipos:
                w = self.window
                for bi in bpos:
                    for ii in ipos:
                        if abs(bi - ii) <= w:
                            return MatchResult(True, f"broad+impact({w})", {})
        return MatchResult(False, None, {})

# Convenience: build a module-level default matcher from our current catalog.
def build_default_matcher(window: int = 12) -> KeywordMatcher:
    return KeywordMatcher(
        keywords=list(KEYWORD_SET),  # your strict set from categories+domains; override as needed
        broad_terms=BROAD_TERMS_DEFAULT,
        impact_terms=IMPACT_TERMS_DEFAULT,
        window=window,
    )

# Construct once; callers can import DEFAULT_MATCHER or build their own.
DEFAULT_MATCHER: KeywordMatcher = build_default_matcher(window=12)

def decide_with_default_keywords(text: str, title: str = "") -> MatchResult:
    """
    One-liner for quick use in RSS intake:
      res = decide_with_default_keywords(body, title)
    """
    return DEFAULT_MATCHER.decide(text, title)
