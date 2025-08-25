# advisor.py — Sentinel Advisor (Final v2025-08-12 + patches v2025-08-25)
# - Reads enriched alerts (schema aligned)
# - Enforces PHYSICAL+DIGITAL, NOW+PREP, role-specific sections
# - Programmatic domain playbook hits, richer alternatives
# - Mandatory “Because X trend, do Y” line
# - Output guard ensures all sections exist and at least one playbook/alternatives appear
# - NEW (2025-08-25): multi-alert merge, predictive tone from future_risk_probability,
#   source reliability & info-ops flags, soft sports-context guard, proactive monitoring meta.

import os
import json
import logging
import re
from typing import Dict, Any, List, Optional, Tuple

from dotenv import load_dotenv

# -------- LLM clients / prompts (soft imports so advisor always loads) --------
try:
    from xai_client import grok_chat  # type: ignore
except Exception:
    def grok_chat(messages, temperature=0.2):
        return None  # graceful no-op

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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if (OPENAI_API_KEY and OpenAI) else None

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TEMPERATURE = float(os.getenv("ADVISOR_TEMPERATURE", 0.2))

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
        "Tighten badge controls; enforce ‘no tailgating’; monitor privileged access anomalies.",
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

# ---------- Role inference ----------
ROLE_KEYWORDS: Dict[str, List[str]] = {
    "traveler": ["traveler","tourist","visitor","student","backpacker","vacation","holiday"],
    "executive": ["executive","exec","ceo","c-suite","vip","founder","chairman","board"],
    "logistics_driver": ["driver","logistics","truck","fleet","delivery","last-mile","dispatcher"],
    "it_secops": ["it","secops","security engineer","admin","administrator","ciso","sysadmin","sre","devops"],
    "ngo_aid": ["ngo","aid","humanitarian","non-profit","charity","relief","mission"],
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
REQUIRED_HEADERS = [
  r"^ALERT —", r"^BULLETPOINT RISK SUMMARY —",
  r"^TRIGGERS / KEYWORDS —", r"^CATEGORIES / SUBCATEGORIES —",
  r"^SOURCES —", r"^REPORTS ANALYZED —", r"^CONFIDENCE —",
  r"^WHAT TO DO NOW —", r"^HOW TO PREPARE —",
  r"^ROLE-SPECIFIC ACTIONS —", r"^DOMAIN PLAYBOOK HITS —",
  r"^FORECAST —", r"^EXPLANATION —", r"^ANALYST CTA —"
]

def ensure_sections(advisory: str) -> str:
    out = advisory.strip()
    for pat in REQUIRED_HEADERS:
        if not re.search(pat, out, flags=re.MULTILINE):
            header = pat.strip("^$").replace(r"\ ", " ")
            out += f"\n\n{header}\n• [auto] Section added (no content)"
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
    # Remove lines like '• [auto] Section added (no content)' for cleaner UI
    return re.sub(r"\n?• \[auto\] Section added \(no content\)", "", advisory)

def strip_excessive_blank_lines(text: str) -> str:
    # Replace 3+ consecutive newlines with 2 newlines, and strip trailing whitespace
    return re.sub(r'\n{3,}', '\n\n', text).strip()

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
    if isinstance(ic30, int): bits.append(f"incident_count_30d={ic30}")
    if isinstance(anom, bool) and anom: bits.append("anomaly_flag=true")
    if isinstance(p_future, (int, float)): bits.append(f"p_next48h={round(float(p_future), 2)}")
    x = ", ".join(bits) if bits else "recent patterns"

    domains = alert.get("domains") or []
    primary = _first_present(domains)

    action = "tighten posture now (route alternatives, safe havens, MFA/passkeys) and review in 12h"
    if primary == "travel_mobility":
        action = "shift departures ±30 minutes, reroute via secondary arterials, and avoid choke points until checkpoint density <1/day or curfews lift"
    elif primary == "cyber_it":
        action = "enforce passkeys/MFA, geo-fence admin logins, and disable legacy auth for 72h"
    elif primary == "digital_privacy_surveillance":
        action = "travel on a clean device, disable biometric unlock at ports, and avoid untrusted Wi-Fi"
    elif primary == "physical_safety":
        action = "avoid poorly lit choke points after 20:00, use well-lit arterials, and stage near 24/7 venues"
    elif primary == "civil_unrest":
        action = "bypass protest nodes via perimeter streets and adjust movement to off-peak windows"
    elif primary == "terrorism":
        action = "minimize dwell in predictable queues, avoid glass-heavy facades/atriums, and keep distance from crowd cores"
    elif primary == "kfr_extortion":
        action = "vary routes/timings by ±20 minutes, verify ride-hail, and keep hands free for control"
    elif primary == "infrastructure_utilities":
        action = "maintain fuel ≥1/2 tank, carry water/cash, and pre-map alt power/charging"
    elif primary == "environmental_hazards":
        action = "avoid flood-prone underpasses, set AQI alerts, and carry N95 if AQI > 100"
    elif primary == "public_health_epidemic":
        action = "prefer bottled water, carry ORS, and avoid high-risk street food until case counts drop"
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
    # sort by score desc, then future_risk_probability
    def _s(a): 
        try: 
            return (float(a.get("score", 0) or 0), float(a.get("future_risk_probability", 0) or 0))
        except Exception:
            return (0.0, 0.0)
    top = sorted(alerts, key=_s, reverse=True)[:3]
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
    # aggregates
    base["score"] = top[0].get("score", base.get("score"))
    base["label"] = top[0].get("label", base.get("label"))
    base["confidence"] = top[0].get("confidence", base.get("confidence"))
    base["anomaly_flag"] = any(a.get("anomaly_flag", a.get("is_anomaly")) for a in top)
    base["future_risk_probability"] = max([a.get("future_risk_probability") or 0 for a in top] + [0])
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
    # If upstream missed domains, backfill from text
    if not domains:
        t = _join_text(alert.get("title"), alert.get("summary"))
        domains = detect_domains(t) or []
        alert["domains"] = domains

    raw_hits = _programmatic_playbook_hits(domains)
    hits = _filter_hits_by_profile(raw_hits, roles)

    role_blocks: Dict[str, List[str]] = {}
    for r in roles:
        role_blocks[r] = _role_actions_for(domains, r)

    anomaly = alert.get("anomaly_flag", alert.get("is_anomaly"))
    next_review = _monitoring_cadence(alert.get("trend_direction") or "stable", bool(anomaly), roles, alert.get("future_risk_probability"))

    payload = {
        "region": alert.get("region") or alert.get("city") or alert.get("country"),
        "city": alert.get("city"),
        "country": alert.get("country"),
        "category": alert.get("category") or alert.get("threat_label"),
        "subcategory": alert.get("subcategory") or "Unspecified",
        "label": alert.get("label"),
        "score": alert.get("score"),
        "confidence": alert.get("confidence"),
        "domains": domains,
        "reports_analyzed": alert.get("reports_analyzed") or alert.get("num_reports") or 1,
        "sources": _normalize_sources(alert.get("sources") or []),
        "incident_count_30d": alert.get("incident_count_30d") if alert.get("incident_count_30d") is not None else "n/a",
        "recent_count_7d": alert.get("recent_count_7d") if alert.get("recent_count_7d") is not None else "n/a",
        "baseline_avg_7d": alert.get("baseline_avg_7d") if alert.get("baseline_avg_7d") is not None else "n/a",
        "baseline_ratio": alert.get("baseline_ratio") if alert.get("baseline_ratio") is not None else "n/a",
        "trend_direction": alert.get("trend_direction") if alert.get("trend_direction") is not None else "stable",
        "anomaly_flag": anomaly if anomaly is not None else False,
        "cluster_id": alert.get("cluster_id"),
        "early_warning_indicators": alert.get("early_warning_indicators") or [],
        "future_risk_probability": alert.get("future_risk_probability"),
        "domain_playbook_hits": hits,
        "alternatives": _alternatives_if_needed(alert),
        "roles": roles,
        "role_actions": role_blocks,
        "next_review_hours": next_review,
        "profile_data": profile_data or {},
        "user_message": user_message,
        "incident_count": alert.get("incident_count", alert.get("incident_count_30d", "n/a")),
        "threat_type": alert.get("category", alert.get("threat_type", "risk")),
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

# ---------- Main entry ----------
def render_advisory(alert: Dict[str, Any], user_message: str, profile_data: Optional[Dict[str, Any]] = None, plan: str = "FREE") -> str:
    trend_line, action = _build_trend_citation_line(alert)
    input_data, roles, hits = _build_input_payload(alert, user_message, profile_data)
    input_data["trend_citation_line"] = trend_line
    input_data["action"] = action
    input_data["specific_action"] = action  # For prompts using {specific action}

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

    user_content = ADVISOR_STRUCTURED_USER_PROMPT.format(
        user_message=user_message,
        input_data=json.dumps(input_data, ensure_ascii=False),
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

    try:
        advisory = grok_chat(messages, temperature=TEMPERATURE) or ""
    except Exception as e:
        logger.error(f"[Advisor] LLM failed: {e}")
        return _fallback_advisory(alert, trend_line, input_data)

    if trend_line not in advisory:
        advisory += ("\n\n" + trend_line)

    # Add ALTERNATIVES if applicable
    alts = input_data.get("alternatives") or []
    if alts and "ALTERNATIVES —" not in advisory:
        advisory += "\n\nALTERNATIVES —\n" + "\n".join(f"• {a}" for a in alts)

    # Role blocks
    role_blocks = input_data.get("role_actions") or {}
    if role_blocks and "ROLE-SPECIFIC ACTIONS —" not in advisory:
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

    advisory = ensure_sections(advisory)
    advisory = ensure_has_playbook_or_alts(advisory, hits, alts)
    advisory = clean_auto_sections(advisory)
    advisory = strip_excessive_blank_lines(advisory)
    return advisory

def _fallback_advisory(alert: Dict[str, Any], trend_line: str, input_data: Dict[str, Any]) -> str:
    region = input_data.get("region") or "Unknown location"
    risk_level = alert.get("label") or "Unknown"
    threat_type = input_data.get("category") or "Other"
    confidence = int(round(100 * float(alert.get("confidence", 0.7))))
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
    lines.append(f"- Trend: {alert.get('trend_direction','stable')} | 7d/baseline: {alert.get('baseline_ratio','1.0')}x | 30d: {alert.get('incident_count_30d','n/a')}")
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

    lines.append("EXPLANATION —")
    lines.append(f"• {trend_line}")

    lines.append("ANALYST CTA —")
    lines.append("• Reply ‘monitor 12h’ for an auto-check, or request a routed analyst review if risk increases.")

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
        return {"reply": json.dumps(result, ensure_ascii=False), "alerts": alerts}
    except Exception:
        alert = alerts[0] if alerts else {}
        advisory = render_advisory(alert, query, profile)
        return {"reply": advisory, "alerts": alerts}
