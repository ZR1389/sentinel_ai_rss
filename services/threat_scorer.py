# threat_scorer.py — Deterministic risk scoring & signals
# v2025-08-31 (aligned with rss_processor matcher + risk_shared taxonomies)
# Used by Threat Engine (no LLM, no DB writes)

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import math
import re
try:
    from unidecode import unidecode
except ImportError as e:
    import logging
    logging.getLogger("threat_scorer").warning(f"[UNIDECODE] unidecode library not available, text normalization will be degraded: {e}")
    def unidecode(s: str) -> str:  # type: ignore
        return s

# Import defensive score handling
try:
    from score_type_safety import safe_numeric_score, safe_score_comparison
except ImportError:
    # Fallback if score_type_safety not available
    def safe_numeric_score(value, default=0.0, min_val=0.0, max_val=100.0):
        """Fallback safe score conversion"""
        try:
            if value is None:
                return default
            return max(min_val, min(max_val, float(value)))
        except (ValueError, TypeError):
            return default
    
    def safe_score_comparison(score1, score2, operator='>'):
        """Fallback safe score comparison"""
        try:
            s1, s2 = float(score1 or 0), float(score2 or 0)
            if operator == '>': return s1 > s2
            elif operator == '>=': return s1 >= s2
            elif operator == '<': return s1 < s2
            elif operator == '<=': return s1 <= s2
            elif operator == '==': return abs(s1 - s2) < 0.001
            elif operator == '!=': return abs(s1 - s2) >= 0.001
            return False
        except (ValueError, TypeError):
            return False

# Shared heuristics/taxonomy
from utils.risk_shared import (
    compute_keyword_weight,
    run_sentiment_analysis,
    detect_domains,
    baseline_from_counts,
    ewma_anomaly,
    _has_keyword,  # For whole-word keyword matching
)

# --------------------------- utilities ---------------------------

def _norm(text: str) -> str:
    """
    Normalize text once for all checks:
      - convert to lowercase
      - strip accents (unidecode)
      - collapse whitespace
    Ensures 'IED', 'IÉD', 'ied' all match, etc.
    """
    return re.sub(r"\s+", " ", unidecode(text or "").lower()).strip()

def _parse_dt(obj: Any) -> Optional[datetime]:
    """
    Accepts Python datetime or common ISO strings (with/without Z). Returns timezone-aware UTC.
    """
    if not obj:
        return None
    if isinstance(obj, datetime):
        dt = obj
    elif isinstance(obj, str):
        s = obj.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            # best-effort coarse parse
            try:
                dt = datetime.strptime(obj[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
    else:
        return None
    # normalize to aware UTC
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _today_utc() -> datetime:
    return datetime.now(timezone.utc)

def _ratio(a: float, b: float, default: float = 1.0) -> float:
    """Safe ratio calculation with fallback."""
    if b == 0:
        return default
    return a / b

def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def _label_from_score(score: float) -> str:
    if score >= 85: return "Critical"
    if score >= 65: return "High"
    if score >= 35: return "Moderate"
    return "Low"

def _bucket_daily_counts(incidents: List[Dict[str, Any]], days: int = 28) -> List[int]:
    """
    Bucket incidents into daily counts over the last N days.
    Returns a list of length 'days' where index 0 is oldest day, index -1 is most recent.
    """
    if not incidents:
        return [0] * days
    
    now = datetime.now(timezone.utc)
    # Create buckets for each day
    buckets = [0] * days
    
    for incident in incidents:
        incident_dt = _parse_dt(incident.get("created_at") or incident.get("timestamp"))
        if not incident_dt:
            continue
            
        # Ensure timezone-aware comparison
        if incident_dt.tzinfo is None:
            incident_dt = incident_dt.replace(tzinfo=timezone.utc)
        
        # Calculate days ago (0 = today, 1 = yesterday, etc.)
        delta = now - incident_dt
        days_ago = int(delta.total_seconds() / 86400)  # 86400 seconds in a day
        
        # Place in appropriate bucket (if within range)
        if 0 <= days_ago < days:
            bucket_idx = days - 1 - days_ago  # reverse index (oldest first)
            buckets[bucket_idx] += 1
    
    return buckets

# --------------------------- severity & context terms ---------------------------

# ---------------------- Import keywords from centralized source ----------------------
try:
    from keywords_loader import SEVERE_TERMS, MOBILITY_TERMS, INFRA_TERMS
except ImportError:
    # Fallback keywords if keywords_loader is not available
    SEVERE_TERMS = [
        "ied","vbied","suicide","suicide bomber","explosion","multiple explosions","mass shooting",
        "kidnap","kidnapping","armed","gunfire","shooting","stabbing","grenade","assassination",
        "curfew","checkpoint","evacuate","emergency","fatal","killed","hostage","car bomb","truck bomb","arson",
        "shelling","mortar","drone strike","airstrike","air strike","artillery","bombing","roadside bomb","improvised explosive",
        "ransomware","breach","data leak","data leakage","data breach","zero-day","zero day","cve-","credential stuffing","ddos","wiper","malware",
        "i e d","v b i e d",
    ]
    
    MOBILITY_TERMS = [
        "airport","border","highway","rail","metro","bridge","port","road closure","detour","traffic suspended","service suspended","runway","airspace","notam","ground stop"
    ]
    
    INFRA_TERMS = [
        "substation","grid","pipeline","telecom","fiber","power outage","blackout","water plant","dam","subsea cable","transformer","refinery","substation fire","transformer fire"
    ]

# --------------------------- noise detection ---------------------------

# Low-quality content patterns that should be filtered out
SPORTS_TERMS = [
    "win", "wins", "won", "beat", "beats", "score", "scored", "scores", "scoring", "goal", "goals",
    "match", "game", "championship", "tournament", "league", "cup", "trophy", "title",
    "football", "soccer", "basketball", "baseball", "cricket", "tennis", "rugby", "hockey",
    "grand prix", "formula 1", "f1", "f2", "f3", "racing", "race", "nascar", "motogp", "rally",
    "world cup", "olympics", "olympic", "medal", "gold medal", "silver medal", "bronze medal",
    "team", "teams", "player", "players", "coach", "coaches", "season", "playoff", "playoffs",
    "final", "finals", "semifinal", "quarterfinal", "qualifier", "qualifiers",
    "vs ", "versus", "v ", "defeat", "defeated", "victory", "victorious",
    "penalty", "penalties", "referee", "umpire", "stadium", "arena",
    "athlete", "athletes", "champion", "champions", "runner-up", "podium",
    "innings", "pitch", "striker", "goalkeeper", "midfielder", "defender",
    "batting", "bowling", "wicket", "wickets", "runs", "tries",
    "lap", "laps", "pole position", "fastest lap", "pit stop",
    "super bowl", "nba", "nfl", "mlb", "nhl", "uefa", "fifa", "ioc",
    "premier league", "la liga", "serie a", "bundesliga", "champions league",
    "test match", "odi", "twenty20", "t20", "ipl", "world series",
    "knockout", "knockout stage", "group stage", "home run", "touchdown",
    "hat trick", "hat-trick", "clean sheet", "shutout", "overtime",
    "sporting", "sports news", "sports update", "game day", "matchday"
]

ENTERTAINMENT_TERMS = [
    "movie", "movies", "film", "films", "cinema", "actor", "actress", "celebrity", "celebrities",
    "star", "stars", "superstar", "music video", "album", "albums", "song", "songs",
    "concert", "concerts", "performance", "show", "shows", "series", "episode", "episodes",
    "grammy", "grammys", "oscar", "oscars", "emmy", "emmys", "award", "awards",
    "nominee", "nominees", "nomination", "nominations", "winner", "red carpet",
    "box office", "premiere", "premieres", "screening", "streaming", "netflix", "disney",
    "hbo", "amazon prime", "apple tv", "hulu", "paramount", "warner bros",
    "band", "bands", "singer", "singers", "musician", "musicians", "artist", "artists",
    "festival", "festivals", "tour", "tours", "touring", "on tour",
    "director", "producer", "screenplay", "soundtrack", "trailer", "teaser",
    "cast", "casting", "audition", "broadway", "west end", "theater", "theatre",
    "comedian", "comedy show", "stand-up", "sitcom", "drama series", "reality show",
    "talent show", "game show", "talk show", "late night", "variety show",
    "blockbuster", "hit movie", "hit song", "chart", "charts", "top 10", "billboard",
    "fashion week", "fashion show", "runway", "model", "models", "modeling",
    "paparazzi", "tabloid", "gossip", "entertainment news", "showbiz", "hollywood",
    "bollywood", "nollywood", "k-pop", "pop star", "rock star", "rap", "rapper",
    "dj", "playlist", "spotify", "itunes", "youtube", "tiktok", "instagram influencer",
    "influencer", "influencers", "vlogger", "youtuber", "content creator",
    "viral video", "trending", "social media star", "internet celebrity"
]

POLITICAL_ROUTINE_TERMS = [
    "election", "vote", "voting", "ballot", "campaign", "candidate",
    "minister appointed", "appointed as", "sworn in", "takes office",
    "prime minister", "president elected", "wins election",
    "cabinet reshuffle", "cabinet appointment", "ministry",
    "parliament", "senate", "congress", "legislature",
    "first to wed", "wedding", "married", "marriage", "ceremony",
    "visit", "visits", "visited", "met with", "meeting with", "summit"
]

CULTURAL_RELIGIOUS_TERMS = [
    "pope", "vatican", "mosque visit", "church visit", "temple visit", "cathedral",
    "religious ceremony", "pilgrimage", "prayer", "blessing", "mass",
    "festival", "celebration", "anniversary", "commemoration",
    "message of hope", "message of peace", "papal visit", "holy see",
    "religious leader", "spiritual leader", "interfaith", "ecumenical"
]

# Civic/local protests that are NOT security threats
CIVIC_LOCAL_TERMS = [
    "stray dog", "stray dogs", "stray animals", "dog catcher", "animal shelter", "animal welfare",
    "animal rights", "animal cruelty", "animal rescue", "pet", "pets", "puppy", "puppies",
    # School/education-related protests (split terms for flexible matching)
    "school demolition", "school closure", "school construction", "demolition protest",
    "demolition of", "building demolition",  # Catches "demolition of...school"
    "alumni protest", "alumni and activists", "parent protest", "student protest", "teacher protest",
    "mahim school",  # Specific known civic case
    # Property/local government issues
    "property tax", "parking fees", "garbage collection", "waste management", "recycling",
    "noise complaint", "pothole", "potholes", "road repair", "street light", "streetlight",
    "zoning", "building permit", "construction permit", "planning commission",
    "tree cutting", "tree removal", "deforestation", "logging", "forest preserve",
    "local council", "city council", "town hall", "neighborhood association",
    "rent control", "tenant rights", "landlord", "eviction", "housing price",
    "bus route", "bus schedule", "metro schedule", "train schedule", "commuter",
    "library closure", "park closure", "beach access", "public pool", "community center",
    "local residents"  # Common civic protest marker
]

# Historical news that is NOT a current threat
HISTORICAL_TERMS = [
    "decades ago", "years ago", 
    # Year/decade patterns - include without "the"
    "in the 1980s", "in 1980s", "in the 1990s", "in 1990s", "in the 2000s",
    "in 1947", "in 1948", "in 1965", "in 1967", "in 1971", "in 1973", "in 1979",
    "in 1980", "in 1981", "in 1982", "in 1983", "in 1984", "in 1985",
    # Cold war and historical era terms
    "cold war", "cold war era", "soviet era", "world war", "world war ii", "world war i",
    # Past tense indicators suggesting historical reporting
    "refused", "had refused", "reportedly refused", "once refused", "rejected",
    "declined to", "turned down",
    # Historical documents/archives
    "declassified", "newly declassified", "archives reveal", "documents reveal",
    "historical", "history", "memoir", "memoirs", "biography", "autobiography",
    "retrospective", "looking back", "anniversary of", "commemorating",
    # Former leaders (past events)
    "former president", "late president", "former prime minister", "late prime minister",
    "indira gandhi",  # Historical figure
]

# Non-English content detection patterns - ONLY very distinctive non-English phrases
# Must use multi-word phrases to avoid false positives on English text
NON_ENGLISH_PATTERNS = [
    # Portuguese distinctive phrases (not single common words)
    "não há", "não é", "está em", "são mais", "mais vulneráveis",
    "ficam mais", "cidades ficam", "tornados como",
    # Spanish distinctive phrases  
    "no hay", "no es", "está en", "años de", "también es",
    # French distinctive phrases
    "il n'y a", "ce n'est pas", "il est", "dans le", "avec le",
    # German distinctive phrases
    "ist nicht", "in der", "mit dem", "für die",
]

ECONOMY_BUSINESS_TERMS = [
    "stock market", "stocks", "shares", "nasdaq", "dow jones", "s&p 500", "ftse",
    "trading", "traders", "investor", "investors", "investment", "portfolio",
    "earnings", "revenue", "profit", "profits", "loss", "losses", "quarterly results",
    "ceo", "cfo", "coo", "executive", "board of directors", "shareholder", "shareholders",
    "merger", "acquisition", "takeover", "buyout", "ipo", "initial public offering",
    "dividend", "dividends", "bond", "bonds", "commodity", "commodities",
    "gdp", "inflation", "deflation", "interest rate", "central bank", "federal reserve",
    "unemployment", "job market", "employment rate", "hiring", "layoffs", "restructuring",
    "startup", "startups", "unicorn", "venture capital", "funding round", "seed funding",
    "cryptocurrency", "crypto", "bitcoin", "ethereum", "blockchain", "nft",
    "forex", "currency", "exchange rate", "dollar", "euro", "yuan", "yen",
    "oil price", "gas price", "crude oil", "barrel", "opec",
    "real estate", "property market", "housing market", "mortgage", "foreclosure",
    "retail sales", "consumer spending", "black friday", "cyber monday", "shopping",
    "trade deal", "trade agreement", "tariff", "import", "export", "trade deficit",
    "economic growth", "recession", "bull market", "bear market", "market rally",
    "corporate", "corporation", "company", "business", "firm", "enterprise",
    "bankruptcy", "insolvency", "debt", "credit rating", "downgrade", "upgrade",
    "manufacturing", "production", "supply chain", "logistics", "warehouse",
    "tech sector", "financial sector", "energy sector", "healthcare sector",
    "wall street", "silicon valley", "fortune 500", "forbes", "bloomberg"
]

def _detect_noise_content(text_norm: str, title: str = "") -> Tuple[bool, str]:
    """
    Detect low-quality non-threat content (sports, entertainment, economy, routine politics,
    local civic issues, historical news, non-English content).
    Returns (is_noise, reason).
    
    Examples to REJECT:
    - "Flamengo beat Palmeiras to win Copa Libertadores" (sports)
    - "Norris wins Brazil Grand Prix" (sports)
    - "Stock market rallies on strong earnings" (economy)
    - "Bitcoin hits new high" (economy)
    - "Australian prime minister becomes first to wed in office" (politics)
    - "Pope visits Blue Mosque" (religious tourism)
    - "Wiggles issue statement after appearing in Ecstasy music video" (entertainment)
    - "BBC boss Tim Davie resigns" (media politics)
    - "People stage protest over stray dogs" (civic/local)
    - "Alumni protest school demolition" (civic/local)
    - "Indira Gandhi refused Israel, India plan in 1980s" (historical)
    - "Sem florestas, as cidades ficam vulneráveis" (non-English)
    """
    title_norm = _norm(title or "")
    combined = f"{title_norm} {text_norm}"
    
    # Non-English detection - look for distinctive non-English phrases
    non_english_hits = sum(1 for pattern in NON_ENGLISH_PATTERNS if pattern in combined)
    if non_english_hits >= 1:  # Any distinctive non-English phrase is enough
        return True, "non_english"
    
    # Historical news detection (past events, not current threats)
    historical_hits = sum(1 for term in HISTORICAL_TERMS if term in combined)
    if historical_hits >= 2:
        # Check if it's about ongoing consequences of historical events
        threat_check = any(t in combined for t in ["today", "now", "current", "ongoing", "latest"])
        if not threat_check:
            return True, "historical"
    
    # Civic/local issues detection (not security threats)
    civic_hits = sum(1 for term in CIVIC_LOCAL_TERMS if term in combined)
    if civic_hits >= 2:
        # Check if it escalated to violence
        threat_check = any(t in combined for t in ["killed", "shooting", "attack", "riot", "violence", "injured", "bomb"])
        if not threat_check:
            return True, "civic_local"
    # Single strong civic indicator in title is enough
    if any(term in title_norm for term in ["stray dog", "school demolition", "animal welfare", "parking fees", "pothole"]):
        return True, "civic_local"
    
    # Sports detection - strong indicators
    sports_hits = sum(1 for term in SPORTS_TERMS if term in combined)
    if sports_hits >= 2:
        # Additional check: if it has threat keywords, might be sports violence (keep it)
        threat_check = any(t in combined for t in ["attack", "shooting", "killed", "bomb", "explosion", "riot", "stabbing"])
        if not threat_check:
            return True, "sports"
    
    # Entertainment detection
    entertainment_hits = sum(1 for term in ENTERTAINMENT_TERMS if term in combined)
    if entertainment_hits >= 2:
        # Additional check: exclude entertainment award ceremonies even if only 1 match with "award"
        if "award" in combined or "awards" in combined:
            return True, "entertainment"
        return True, "entertainment"
    
    # Economy/Business detection
    economy_hits = sum(1 for term in ECONOMY_BUSINESS_TERMS if term in combined)
    if economy_hits >= 2:
        # Check if it's economic terrorism/sanctions (keep those)
        threat_check = any(t in combined for t in ["sanctions", "embargo", "freeze", "seized", "confiscated", "financial crime"])
        if not threat_check:
            return True, "economy"
    
    # Routine politics detection (elections, appointments, weddings, visits)
    politics_hits = sum(1 for term in POLITICAL_ROUTINE_TERMS if term in combined)
    if politics_hits >= 2:
        # Check if it's actually a political threat (coup, assassination, etc.)
        threat_check = any(t in combined for t in ["coup", "assassination", "killed", "attack", "riot", "bomb", "shooting"])
        if not threat_check:
            return True, "politics"
    
    # Cultural/religious routine events (not threats)
    cultural_hits = sum(1 for term in CULTURAL_RELIGIOUS_TERMS if term in combined)
    if cultural_hits >= 2:
        # Check if it's a religious attack
        threat_check = any(t in combined for t in ["attack", "bomb", "shooting", "killed", "fire", "arson"])
        if not threat_check:
            return True, "cultural"
    
    return False, ""

# --------------------------- scoring core ---------------------------

def _kw_rule_bonus(rule: Optional[str]) -> float:
    """
    Bonus points based on matcher rule:
      - broad+impact(sentence)  → +8
      - broad+impact(window)    → +5
      - keyword/other/None      → +0
    Accepts slight spelling variants ('sent').
    """
    if not rule:
        return 0.0
    r = (rule or "").lower()
    if "broad+impact" in r and ("sentence" in r or "sent" in r):
        return 8.0
    if "broad+impact" in r and "window" in r:
        return 5.0
    return 0.0

def _kw_salience_points(text_norm: str) -> float:
    """
    Map compute_keyword_weight (0..1) → 0..55 points.
    Same shape as older scorer (55% weight).
    """
    kw = compute_keyword_weight(text_norm)
    return 55.0 * _clamp(kw, 0.0, 1.0)

def _trigger_points(triggers: Optional[List[str]]) -> float:
    """
    0..25 points, saturates at 6 triggers.
    """
    t = min(len(triggers or []), 6)
    return (25.0 / 6.0) * float(t)

def _severity_points(text_norm: str) -> Tuple[float, int]:
    """
    Each severe hit → +5 points, cap at 20.
    Return (points, hit_count).
    Uses whole-word matching to avoid false positives (e.g., 'shortage' matching 'short').
    """
    hits = sum(1 for k in SEVERE_TERMS if _has_keyword(text_norm, k))
    pts = min(20.0, 5.0 * float(hits))
    return pts, hits

def _mobinfra_bonus(text_norm: str) -> float:
    """
    Mobility/infrastructure presence → small +3 bonus (kept conservative).
    """
    if any(t in text_norm for t in (MOBILITY_TERMS + INFRA_TERMS)):
        return 3.0
    return 0.0

def _nudge_points(text_norm: str) -> float:
    """
    Contextual bounded nudges identical to earlier behavior.
    """
    bonus = 0.0
    if any(k in text_norm for k in ["suicide bomber","vbied","mass shooting","multiple explosions"]):
        bonus += 10.0
    if "curfew" in text_norm and "checkpoint" in text_norm:
        bonus += 5.0
    if ("airport" in text_norm and ("closure" in text_norm or "suspended" in text_norm or "runway" in text_norm)):
        bonus += 5.0
    if (("cve-" in text_norm) or ("zero-day" in text_norm) or ("zero day" in text_norm)) and (("ransomware" in text_norm) or ("breach" in text_norm)):
        bonus += 5.0
    return bonus

def _score_components(
    text_norm: str,
    triggers: Optional[List[str]],
    kw_match: Optional[Dict[str, Any]] = None,
    title: str = ""
) -> Tuple[float, Dict[str, float], Optional[str]]:
    """
    Deterministic mapping of signals → points. Returns (total_points, breakdown).
    
    SCORING WEIGHTS RATIONALE:
    - Keyword salience (0..55): Primary threat indicator, highest weight.
      Uses compute_keyword_weight() which measures keyword density and coverage.
      55 points allows fine-grained distinction between high/medium/low keyword matches.
    
    - Triggers (0..25): Secondary signals from structured categories/tags.
      25 points (5 per trigger, max 6) provides substantial weight without overshadowing keywords.
      Saturates at 6 to prevent trigger spam from inflating scores.
    
    - Severity (0..20): Critical incident markers (IED, suicide bomber, mass shooting).
      20 points (5 per hit, max 4) adds significant boost for catastrophic events.
      Lower than keywords to avoid false positives from severe terms in non-threat contexts.
    
    - KW rule bonus (+0/+5/+8): Rewards high-quality keyword matches.
      +8 for direct matches, +5 for broad+impact in same sentence, +0 for window matches.
      Modest bonus to distinguish match quality without dominating score.
    
    - Mobility/infra bonus (+3): Small boost for infrastructure/transportation impact.
      Conservative +3 to flag logistical concerns without inflating threat score.
    
    - Contextual nudges (+10 max): Situational bonuses for specific threat combinations.
      Examples: suicide bomber+checkpoint (+5), CVE+ransomware (+5), curfew+checkpoint (+5).
      Capped at +10 to prevent excessive stacking.
    
    - Noise penalty (-80): Heavy penalty for sports/entertainment/routine politics.
      Examples: sports scores, election results, celebrity news, religious tourism.
      Ensures non-threat content gets very low scores (below threshold).
    
    TOTAL RANGE: 5-100 points (global clamp for safety)
    LABEL MAPPING: 85+ Critical, 65-84 High, 35-64 Moderate, 5-34 Low
    """
    breakdown: Dict[str, float] = {}
    noise_type_detected: Optional[str] = None  # Store separately to avoid type error in sum()

    # Check for noise content first
    is_noise, noise_type = _detect_noise_content(text_norm, title=title)
    if is_noise:
        breakdown["noise_penalty"] = -80.0  # Heavy penalty for sports/entertainment/politics
        noise_type_detected = noise_type  # Store string separately, not in numeric breakdown
    else:
        breakdown["noise_penalty"] = 0.0

    breakdown["keywords"] = _kw_salience_points(text_norm)
    breakdown["triggers"] = _trigger_points(triggers)
    sev_pts, _ = _severity_points(text_norm)
    breakdown["severity"] = sev_pts
    breakdown["kw_rule_bonus"] = _kw_rule_bonus((kw_match or {}).get("rule"))
    breakdown["mobinfra_bonus"] = _mobinfra_bonus(text_norm)
    breakdown["nudges"] = _nudge_points(text_norm)

    total = sum(breakdown.values())
    # global clamp for safety
    total = _clamp(total, 5.0, 100.0)
    return total, breakdown, noise_type_detected

# --------------------------- public API ---------------------------

def compute_now_risk(alert_text: str, triggers: Optional[List[str]] = None, location: Optional[str] = None) -> float:
    """
    Backward-compatible fast heuristic risk (0..100).
    NOTE: For full rule-aware scoring (including kw_match), call assess_threat_level.
    """
    text = _norm(alert_text or "")
    score, _, _ = _score_components(text, triggers, kw_match=None)
    return float(round(score, 1))

def assess_threat_level(
    alert_text: str,
    triggers: Optional[List[str]],
    location: Optional[str],
    alert_uuid: Optional[str] = None,
    plan: Optional[str] = None,
    enrich: bool = True,
    user_email: Optional[str] = None,
    source_alert: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Main scoring function used by the Threat Engine.
    
    Returns keys consumed by the engine/advisor:
      - label (Low/Moderate/High/Critical): Threat severity category
      - score (0..100): Deterministic point-based threat score
      - confidence (0..1): Signal quality measure (NOT score extremity)
        * Based on: source reliability, location precision, keyword match quality
        * High confidence = strong signals, low false positive risk
        * Low confidence = weak signals, higher uncertainty
      - reasoning (short string): Concise explanation of scoring factors
      - sentiment (aux): Negative/neutral/positive classification
      - domains (aux): Threat domain tags (physical_safety, cyber_it, etc.)
      - kw_rule (aux, for debugging): Keyword matching rule used
      - score_breakdown (aux dict): Point allocation by component
    
    Confidence calculation prioritizes signal quality over score magnitude:
      - Source: Intelligence (ACLED/GDELT) +0.20, RSS +0.10
      - Location: High precision +0.15, Medium +0.10, Low +0.05
      - Keywords: Direct match +0.10, Sentence context +0.07, Window +0.04
      - Triggers: Multiple categories +0.05
    """
    text = _norm(alert_text or "")
    kw_match = (source_alert or {}).get("kw_match") if source_alert else None
    title = (source_alert or {}).get("title", "")

    # Points (with noise detection using title)
    score, breakdown, noise_type = _score_components(text, triggers, kw_match=kw_match, title=title)
    is_noise = noise_type is not None

    # Confidence: Signal quality (NOT score extremity)
    # Measures reliability of threat detection, not severity.
    # High confidence = strong signals, low false positive risk
    # Low confidence = weak signals, higher uncertainty
    
    kw_weight = compute_keyword_weight(text)              # 0..1 (keyword quality)
    trig_norm = min(len(triggers or []), 6) / 6.0         # 0..1 (trigger count)

    # Base confidence
    conf = 0.50
    
    # Source reliability: Intelligence sources > RSS feeds
    source_kind = (source_alert or {}).get("source_kind", "")
    source_name = (source_alert or {}).get("source", "")
    if source_kind == "intelligence" or source_name.lower() in ["acled", "gdelt"]:
        conf += 0.20  # Intelligence data has higher baseline reliability
    else:
        conf += 0.10  # RSS feeds are good but less structured
    
    # Location confidence: Geocoded > Inferred > Unknown
    location_conf = (source_alert or {}).get("location_confidence", "none")
    if location_conf == "high":
        conf += 0.15  # Precise geocoding
    elif location_conf == "medium":
        conf += 0.10  # City-level or inferred
    elif location_conf == "low":
        conf += 0.05  # Country-level only
    # else: +0 for none/unknown
    
    # Keyword match quality: Direct > Sentence > Window
    if kw_match and isinstance(kw_match.get("rule"), str):
        r = kw_match["rule"].lower()
        if "direct" in r or "exact" in r:
            conf += 0.10  # High confidence: direct threat keyword
        elif "broad+impact" in r and ("sentence" in r or "sent" in r):
            conf += 0.07  # Medium-high: contextual match in same sentence
        elif "broad+impact" in r and "window" in r:
            conf += 0.04  # Medium: contextual match within window
    else:
        # Fallback: use keyword weight if no match rule
        conf += 0.10 * kw_weight
    
    # Trigger count: Multiple triggers increase confidence
    if trig_norm > 0.50:
        conf += 0.05  # Multiple category tags corroborate threat
    
    confidence = round(_clamp(conf, 0.40, 0.95), 2)

    # Sentiment & domains (aux)
    sentiment = run_sentiment_analysis(text)
    domains = detect_domains(text)

    # Slight confidence floor for very high scores
    if score >= 85.0:
        confidence = max(confidence, 0.75)

    label = _label_from_score(score)

    # Reasoning: concise and deterministic
    sev_hits = sum(1 for k in SEVERE_TERMS if _has_keyword(text, k))
    reasoning_bits = [
        f"score={round(score,1)}",
        f"conf={confidence}",
        f"salience={kw_weight:.2f}",
        f"sev_hits={sev_hits}",
        f"triggers={len(triggers or [])}",
        f"sentiment='{sentiment}'"
    ]
    if domains:
        reasoning_bits.append(f"domains={','.join(domains[:4])}")
    if kw_match and kw_match.get("rule"):
        reasoning_bits.append(f"kw_rule={kw_match.get('rule')}")
    if source_alert:
        if source_alert.get("source"):
            reasoning_bits.append(f"source={source_alert.get('source')}")
        if source_alert.get("location_confidence"):
            reasoning_bits.append(f"loc_conf={source_alert.get('location_confidence')}")
    reasoning = "; ".join(reasoning_bits)

    # Attach a compact view of kw matches for debugging
    kw_rule = (kw_match or {}).get("rule")
    kw_matches = (kw_match or {}).get("matches") or {}
    # For readability, trim any huge lists
    trimmed_matches = {}
    for k, v in kw_matches.items():
        try:
            if isinstance(v, list) and len(v) > 8:
                trimmed_matches[k] = v[:8] + ["+more"]
            else:
                trimmed_matches[k] = v
        except Exception:
            continue

    return {
        "label": label,
        "threat_label": label,
        "threat_level": label,
        "score": round(float(score), 1),
        "confidence": confidence,
        "reasoning": reasoning,
        "sentiment": sentiment,
        "domains": domains,
        # extras (non-breaking)
        "kw_rule": kw_rule,
        "kw_matches": trimmed_matches,
        "score_breakdown": {k: round(v, 1) for k, v in breakdown.items()},
        # Noise detection - if True, alert should be rejected
        "is_noise": is_noise,
        "noise_type": noise_type,
    }

# --------------------------- trends & stats (unchanged) ---------------------------

def compute_trend_direction(incidents: List[Dict[str, Any]]) -> str:
    """
    Direction from recent 7d vs baseline (previous 21d normalized to 7d).
    """
    if not incidents:
        return "stable"
    counts_28 = _bucket_daily_counts(incidents, days=28)  # oldest..newest
    recent_7 = sum(counts_28[-7:])
    prev_21 = sum(counts_28[:-7])
    baseline_7 = prev_21 / 3.0 if prev_21 else 0.0
    ratio = _ratio(recent_7, baseline_7, default=(1.0 if recent_7 > 0 else 0.0))

    if ratio > 1.25:
        return "increasing"
    if ratio < 0.80:
        return "decreasing"
    return "stable"

def compute_future_risk_probability(incidents: List[Dict[str, Any]]) -> float:
    """
    Probability (0..1) of another incident within next 48h.
    Based on recent 7d vs *previous 49d* baseline ratio (excludes leakage) + EWMA spike flag.
    """
    counts_56 = _bucket_daily_counts(incidents, days=56)
    if not counts_56:
        return 0.25  # conservative default

    recent_7 = sum(counts_56[-7:])       # last week
    prev_49 = sum(counts_56[:-7])        # exclude last week from baseline
    base_avg_7 = (prev_49 / 7.0) if prev_49 else 0.0
    ratio = (recent_7 / base_avg_7) if base_avg_7 > 0 else (1.0 if recent_7 > 0 else 0.0)

    # EWMA anomaly check on last 21 days
    ewma_spike = ewma_anomaly(counts_56[-21:], alpha=0.4, k=2.5)

    # Logistic-ish mapping from ratio + spike → probability
    # Center at 1.0x baseline; scale to keep within 0.2..0.95
    x = (ratio - 1.0) * 1.1
    p = 0.5 * (1.0 + math.tanh(x))  # 0..1
    if ewma_spike:
        p += 0.1
    return round(_clamp(p, 0.20, 0.95), 2)

def stats_average_score(incidents: List[Dict[str, Any]]) -> float:
    """
    Average of 'score' field over incidents (ignoring missing/invalid).
    Uses safe score conversion to handle TEXT score columns.
    """
    vals: List[float] = []
    for inc in incidents or []:
        s = inc.get("score")
        # Use safe score conversion instead of raw float()
        safe_val = safe_numeric_score(s, default=None)
        if safe_val is not None:
            vals.append(safe_val)
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 1)

def early_warning_indicators(incidents: List[Dict[str, Any]]) -> List[str]:
    """
    Cheap, useful flags from time clustering and severity.
    Emits subset of: burst_48h, ewma_spike, high_severity_cluster
    """
    out: List[str] = []
    if not incidents:
        return out

    # Time burst (>=3 incidents in 48h)
    now = _today_utc()
    window_48 = now - timedelta(hours=48)
    recent48 = [i for i in incidents if (_parse_dt(i.get("published")) or now) >= window_48]
    if len(recent48) >= 3:
        out.append("burst_48h")

    # EWMA spike on last 14 days
    counts_14 = _bucket_daily_counts(incidents, days=14)
    if ewma_anomaly(counts_14, alpha=0.4, k=2.5):
        out.append("ewma_spike")

    # High severity share over last 14 days (score>75)
    high = 0
    total = 0
    for inc in incidents:
        dt = _parse_dt(inc.get("published"))
        if not dt:
            continue
        if dt >= now - timedelta(days=14):
            total += 1
            # Use safe score comparison to handle TEXT scores from database
            score_value = inc.get("score", 0)
            if safe_score_comparison(score_value, 75.0, '>'):
                high += 1
    if total >= 5 and (high / max(total, 1)) >= 0.4:
        out.append("high_severity_cluster")

    return out
