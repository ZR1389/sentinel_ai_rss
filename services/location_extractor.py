"""
location_extractor.py — Extract location intent from free-text user queries.

Primary approach:
- spaCy NER (GPE/LOC) to detect place mentions
- pycountry to resolve country names (with fuzzy matching)
- city_utils to fuzzy-match known cities and map to country when possible

Robust fallbacks:
- If spaCy model unavailable, use simple regex + pycountry + city_utils

Returns dict with keys: {city, region, country, method, notes}
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple
import logging
import re

logger = logging.getLogger(__name__)

# Optional deps (guarded)
try:
    import spacy  # type: ignore
except Exception:
    spacy = None  # type: ignore

try:
    import pycountry  # type: ignore
except Exception:
    pycountry = None  # type: ignore

try:
    from city_utils import get_country_for_city, fuzzy_match_city
except Exception:
    def get_country_for_city(city: str) -> Optional[str]:
        return None
    def fuzzy_match_city(text: str) -> Optional[str]:
        return None

_nlp = None
def _ensure_spacy():
    global _nlp
    if _nlp is not None:
        return _nlp
    if spacy is None:
        return None
    try:
        _nlp = spacy.load("en_core_web_sm")
        return _nlp
    except Exception as e:
        logger.warning("spaCy model en_core_web_sm not loaded: %s", e)
        return None


def _resolve_country(name: str) -> Optional[str]:
    if not name:
        return None
    s = name.strip()
    # Direct exact
    if pycountry:
        try:
            # search_fuzzy raises on miss
            match = pycountry.countries.search_fuzzy(s)
            if match:
                return match[0].name
        except Exception:
            # try common name lookup
            try:
                for c in pycountry.countries:
                    if c.name.lower() == s.lower():
                        return c.name
            except Exception:
                pass
    # Common manual aliases (minimal set)
    aliases = {
        "uk": "United Kingdom",
        "u.k.": "United Kingdom",
        "usa": "United States",
        "u.s.a.": "United States",
        "us": "United States",
        "u.s.": "United States",
        "uae": "United Arab Emirates",
    }
    return aliases.get(s.lower())


def extract_location_from_query(query: str) -> Dict[str, Optional[str]]:
    """
    Extract location intent from user query.

    Returns:
      {
        'city': Optional[str],
        'region': Optional[str],
        'country': Optional[str],
        'method': str,            # 'spacy', 'regex', 'fallback'
        'notes': Optional[str],
      }
    """
    res: Dict[str, Optional[str]] = {
        "city": None,
        "region": None,
        "country": None,
        "method": None,  # type: ignore
        "notes": None,
    }

    q = (query or "").strip()
    if not q:
        res["method"] = "empty"
        return res

    # 1) Try spaCy NER
    nlp = _ensure_spacy()
    if nlp is not None:
        try:
            doc = nlp(q)
            # collect GPE/LOC spans in order
            places = [ent.text.strip() for ent in doc.ents if ent.label_ in ("GPE", "LOC")]
            for place in places:
                # Country first
                country = _resolve_country(place)
                if country:
                    res["country"] = country
                    res["method"] = "spacy"
                    return res
                # Then city
                city = fuzzy_match_city(place) or place
                mapped_country = get_country_for_city(city) if city else None
                if city and mapped_country:
                    res["city"] = city.title()
                    res["country"] = mapped_country
                    res["method"] = "spacy"
                    return res
            # If we had places but couldn't resolve, keep the last as region fallback
            if places:
                res["region"] = places[-1]
                res["method"] = "spacy"
                return res
        except Exception as e:
            logger.debug("spaCy extraction failed: %s", e)

    # 2) Regex heuristics for 'in <place>' patterns
    try:
        m = re.search(r"\b(?:in|for|at|around|near)\s+([A-Z][A-Za-z\-\s]{2,})\b", q)
        if m:
            token = m.group(1).strip()
            # Try country
            country = _resolve_country(token)
            if country:
                res["country"] = country
                res["method"] = "regex"
                return res
            # Try city
            city = fuzzy_match_city(token) or token
            mapped_country = get_country_for_city(city) if city else None
            if city and mapped_country:
                res["city"] = city.title()
                res["country"] = mapped_country
                res["method"] = "regex"
                return res
            # Fallback as region
            res["region"] = token
            res["method"] = "regex"
            return res
    except Exception as e:
        logger.debug("regex extraction failed: %s", e)

    # 3) pycountry last resort on any Capitalized token
    try:
        tokens = re.findall(r"\b([A-Z][A-Za-z]{2,})\b", q)
        for t in tokens:
            country = _resolve_country(t)
            if country:
                res["country"] = country
                res["method"] = "fallback"
                return res
    except Exception:
        pass

    res["method"] = "none"
    return res
