# risk_shared.py — Shared enrichment & analytics (canonical detectors + helpers) • v2025-08-22+patch3 (2025-08-31)
# Used by: RSS Processor, Threat Engine, Scorer, Advisor. No metered LLM calls here.

from __future__ import annotations
import re
import math
import os
import hashlib
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Sequence

try:
    import tiktoken
except ImportError:
    tiktoken = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from unidecode import unidecode
except Exception as e:
    import logging
    logging.getLogger("risk_shared").warning(f"[UNIDECODE] unidecode library not available, text normalization will be degraded: {e}")
    def unidecode(s: str) -> str:  # no-op fallback
        return s

# ---------------------- Import keywords from centralized source ----------------------
try:
    from keywords_loader import (
        CATEGORY_KEYWORDS, SUBCATEGORY_MAP, DOMAIN_KEYWORDS,
        get_all_keywords, get_keywords_by_category, get_keywords_by_domain
    )
except ImportError:
    # Fallback to basic keywords if keywords_loader is not available
    CATEGORY_KEYWORDS: Dict[str, List[str]] = {
        "Crime": ["robbery","assault","shooting","stabbing","murder","burglary","theft","carjacking","homicide","looting","kidnap","kidnapping","abduction","arson","home invasion"],
        "Terrorism": ["ied","vbied","suicide bomber","terrorist","bomb","explosion","martyrdom","blast","grenade","improvised explosive","car bomb","truck bomb","shelling","mortar","drone strike","airstrike","air strike","artillery"],
        "Civil Unrest": ["protest","riot","demonstration","march","sit-in","clash","looting","roadblock","strike"],
        "Cyber": ["ransomware","phishing","malware","breach","ddos","credential","data leak","data leakage","zero-day","zero day","cve","exploit","backdoor","credential stuffing","wiper","data breach"],
        "Infrastructure": ["substation","pipeline","power outage","grid","transformer","telecom","fiber","water plant","facility","sabotage","blackout","subsea cable","dam","bridge","transformer fire"],
        "Environmental": ["earthquake","flood","hurricane","storm","wildfire","heatwave","landslide","mudslide","tornado","cyclone"],
        "Epidemic": ["epidemic","pandemic","outbreak","cholera","dengue","covid","ebola","avian flu"],
        "Other": []
    }
    SUBCATEGORY_MAP: Dict[str, Dict[str, str]] = {}
    DOMAIN_KEYWORDS: Dict[str, List[str]] = {
        "travel_mobility": ["travel","route","road","highway","checkpoint","curfew","airport","border","port","rail","metro"],
        "physical_safety": ["kidnap","abduction","theft","assault","shooting","stabbing","robbery","looting"],
        "cyber_it": ["cyber","hacker","phishing","ransomware","malware","data breach","ddos"]
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
    """
    DEPRECATED: Use location_service_consolidated.detect_location() instead.
    Wrapper around city_utils for backward compatibility.
    """
    import warnings
    warnings.warn(
        "extract_location from risk_shared is deprecated. Use location_service_consolidated.detect_location() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    try:
        # Use consolidated location service
        from location_service_consolidated import detect_location
        result = detect_location(text or "")
        return result.city, result.country
    except Exception:
        # Fallback to original implementation
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
      3) Else, if any broad within 'window' tokens of impact -> HIT ("broad+impact(window)") [default: 15 tokens]
      4) Else -> no hit
    """
    def __init__(self,
                 keywords: Sequence[str],
                 broad_terms: Sequence[str] = BROAD_TERMS_DEFAULT,
                 impact_terms: Sequence[str] = IMPACT_TERMS_DEFAULT,
                 window: int = 15):
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

# Standardized default window - DO NOT CHANGE without updating config.py
COOC_WINDOW_DEFAULT = 12

# Convenience: build a module-level default matcher from our current catalog.
def build_default_matcher(window: int = COOC_WINDOW_DEFAULT) -> KeywordMatcher:
    """Build matcher with canonical keywords."""
    return KeywordMatcher(
        keywords=list(KEYWORD_SET),  # your strict set from categories+domains; override as needed
        broad_terms=BROAD_TERMS_DEFAULT,
        impact_terms=IMPACT_TERMS_DEFAULT,
        window=window,
    )

# Construct once; callers can import DEFAULT_MATCHER or build their own.
DEFAULT_MATCHER: KeywordMatcher = build_default_matcher(window=COOC_WINDOW_DEFAULT)

def decide_with_default_keywords(text: str, title: str = "") -> MatchResult:
    """
    One-liner for quick use in RSS intake:
      res = decide_with_default_keywords(body, title)
    """
    return DEFAULT_MATCHER.decide(text, title)


# ---------------------- Embedding Quota Manager ----------------------

@dataclass
class QuotaMetrics:
    """Track daily embedding usage metrics."""
    daily_tokens: int = 0
    daily_requests: int = 0
    last_reset: Optional[datetime] = None


class EmbeddingManager:
    """
    Manages OpenAI embedding quota and provides fallback mechanisms.
    
    Features:
    - Daily token/request limits with automatic reset
    - Thread-safe quota tracking
    - Fallback to deterministic hash when quota exceeded
    - Configurable limits via environment variables
    """
    
    def __init__(self):
        # Initialize tokenizer if available
        if tiktoken:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        else:
            self.tokenizer = None
            
        from config import CONFIG
        self.quota = QuotaMetrics()
        self.daily_limit = CONFIG.app.embedding_quota_daily
        self.request_limit = CONFIG.app.embedding_requests_daily
        self.lock = threading.Lock()
        
    def _check_quota(self, text: str) -> bool:
        """Check if we have quota for this request."""
        with self.lock:
            now = datetime.utcnow()
            
            # Reset daily counter if needed (check if it's a new day)
            if (self.quota.last_reset is None or 
                (now - self.quota.last_reset).days >= 1):
                self.quota.daily_tokens = 0
                self.quota.daily_requests = 0
                self.quota.last_reset = now
                
            # Calculate tokens for this request
            if self.tokenizer:
                tokens = len(self.tokenizer.encode(text))
            else:
                # Rough estimation: ~4 chars per token
                tokens = len(text) // 4
                
            # Check token limit
            if self.quota.daily_tokens + tokens > self.daily_limit:
                import logging
                logger = logging.getLogger("risk_shared.embedding")
                logger.warning(
                    f"Embedding quota exceeded: {self.quota.daily_tokens + tokens}/{self.daily_limit} tokens"
                )
                return False
                
            # Check request limit
            if self.quota.daily_requests >= self.request_limit:
                import logging
                logger = logging.getLogger("risk_shared.embedding")
                logger.warning(
                    f"Embedding request limit exceeded: {self.quota.daily_requests}/{self.request_limit} requests"
                )
                return False
                
            # Update quota
            self.quota.daily_tokens += tokens
            self.quota.daily_requests += 1
            return True
    
    def get_embedding_safe(self, text: str, client) -> List[float]:
        """
        Get embedding with quota and fallback protection.
        
        Args:
            text: Text to embed
            client: OpenAI client instance
            
        Returns:
            List of embedding floats (either from API or fallback)
        """
        if not text:
            return self._fallback_hash(text)
            
        # Check if we have sufficient quota
        if not self._check_quota(text):
            return self._fallback_hash(text)
            
        try:
            # Attempt API call with timeout
            resp = client.embeddings.create(
                model="text-embedding-3-small",
                input=text[:8192],  # Truncate to model limit
                timeout=10.0
            )
            return resp.data[0].embedding
            
        except Exception as e:
            import logging
            logger = logging.getLogger("risk_shared.embedding")
            logger.error(f"Embedding API error: {e}, using fallback")
            return self._fallback_hash(text)
    
    def _fallback_hash(self, text: str) -> List[float]:
        """
        Generate deterministic hash-based embedding fallback.
        
        Creates a 10-dimensional vector from SHA-1 hash segments.
        Provides consistent results for the same input text.
        """
        if not text:
            # Return zero vector for empty text
            return [0.0] * 10
            
        # Generate SHA-1 hash
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        
        # Convert hex segments to normalized floats
        # Take 4-char hex segments, convert to int, normalize to [0,1]
        return [int(h[i:i+4], 16) % 997 / 997.0 for i in range(0, 40, 4)]
    
    def get_quota_status(self) -> Dict[str, int]:
        """Get current quota usage statistics."""
        with self.lock:
            return {
                "daily_tokens": self.quota.daily_tokens,
                "daily_requests": self.quota.daily_requests,
                "token_limit": self.daily_limit,
                "request_limit": self.request_limit,
                "tokens_remaining": max(0, self.daily_limit - self.quota.daily_tokens),
                "requests_remaining": max(0, self.request_limit - self.quota.daily_requests),
            }


# Global embedding manager instance
embedding_manager = EmbeddingManager()


def get_embedding(text: str, client=None) -> List[float]:
    """
    Get text embedding with quota management and fallback.
    
    Args:
        text: Text to embed
        client: OpenAI client instance (optional)
        
    Returns:
        List of embedding floats
    """
    if client and OpenAI:
        return embedding_manager.get_embedding_safe(text, client)
    else:
        # No client available, use deterministic fallback
        return embedding_manager._fallback_hash(text)
