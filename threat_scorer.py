import os
import uuid
from datetime import datetime
from dotenv import load_dotenv
from xai_client import grok_chat
from openai import OpenAI
from prompts import THREAT_SCORER_SYSTEM_PROMPT

from pathlib import Path
import pickle

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

CRITICAL_KEYWORDS = [
    "assassination", "suicide bombing", "mass shooting", "IED",
    "terrorist attack", "hijacking", "hostage situation", "military raid"
]
HIGH_KEYWORDS = [
    "shooting", "explosion", "gunfire", "kidnapping", "armed attack", "arson", "riot", "violent protest",
    "looting", "bomb threat", "martial law", "state of emergency"
]
MODERATE_KEYWORDS = [
    "protest", "blockade", "roadblock", "robbery", "evacuation", "civil unrest", "theft", "burglary",
    "scam", "fraud", "power outage", "load shedding"
]

CACHE_PATH = Path("threat_scorer_cache.pkl")

def load_cache():
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "rb") as f:
                return pickle.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache):
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(cache, f)

def normalize_threat_label(label):
    label = label.strip().lower()
    if "critical" in label:
        return "Critical"
    elif "high" in label:
        return "High"
    elif "moderate" in label:
        return "Moderate"
    elif "low" in label:
        return "Low"
    else:
        return "Unrated"

def keyword_score_and_label(text):
    lowered = text.lower()
    for kw in CRITICAL_KEYWORDS:
        if kw.lower() in lowered:
            return 100, "Critical", f"Matched critical keyword: '{kw}'"
    for kw in HIGH_KEYWORDS:
        if kw.lower() in lowered:
            return 85, "High", f"Matched high keyword: '{kw}'"
    for kw in MODERATE_KEYWORDS:
        if kw.lower() in lowered:
            return 60, "Moderate", f"Matched moderate keyword: '{kw}'"
    return 30, "Low", "No critical/high/moderate keywords detected"

def estimate_confidence(model_used, label):
    if label == "Critical":
        return 0.99
    if model_used == "rules":
        return 1.0
    elif model_used == "grok-3-mini":
        return 0.88
    elif model_used == "openai":
        return 0.85
    else:
        return 0.5

def assess_threat_level(alert_text, triggers=None, location=None, model_hint=None, review_threshold=60, alert_uuid=None):
    """
    Returns a dict with fields:
        - threat_label: Low/Moderate/High/Critical
        - score: 0-100
        - model_used
        - uuid
        - reasoning
        - review_flag
        - confidence
        - timestamp
        - review_notes
    """
    if not isinstance(alert_text, str):
        alert_text = str(alert_text)
    timestamp = datetime.utcnow().isoformat()

    # Cache: Use alert_uuid as key if provided, else hash of inputs
    cache = load_cache()
    cache_key = alert_uuid or f"{hash(alert_text)}_{hash(str(triggers))}_{hash(str(location))}"
    if cache_key in cache:
        cached_result = cache[cache_key]
        cached_result["timestamp"] = timestamp  # update timestamp for retrieval time
        return cached_result

    assessment_id = alert_uuid or str(uuid.uuid4())
    triggers = triggers or []
    location = location or ""

    # 1. Rules/keyword-based quick check
    score, label, reasoning = keyword_score_and_label(alert_text)
    model_used = "rules"
    review_flag = False
    confidence = None
    llm_errors = []

    # 2. If not critical/high, use LLM for finer scoring and reasoning
    if label in ["Low", "Moderate"]:
        system_prompt = THREAT_SCORER_SYSTEM_PROMPT.format(
            alert_text=alert_text,
            triggers=', '.join(triggers) if triggers else 'None',
            location=location
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": alert_text}
        ]
        # Try Grok first
        try:
            grok_result = grok_chat(messages, temperature=0)
            import json
            parsed = json.loads(grok_result)
            label = normalize_threat_label(parsed.get("label", label))
            score = int(parsed.get("score", score))
            reasoning = parsed.get("reasoning", reasoning)
            confidence = parsed.get("confidence", None)
            model_used = "grok-3-mini"
        except Exception as e:
            llm_errors.append(f"[THREAT_SCORER_ERROR][GROK] {e} | Input: {alert_text}")
            print(llm_errors[-1])
            if openai_client:
                try:
                    response = openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=messages,
                        temperature=0
                    )
                    import json
                    parsed = json.loads(response.choices[0].message.content)
                    label = normalize_threat_label(parsed.get("label", label))
                    score = int(parsed.get("score", score))
                    reasoning = parsed.get("reasoning", reasoning)
                    confidence = parsed.get("confidence", None)
                    model_used = "openai"
                except Exception as e2:
                    llm_errors.append(f"[THREAT_SCORER_ERROR][OPENAI] {e2} | Input: {alert_text}")
                    print(llm_errors[-1])
                    reasoning += f" | [LLM scoring failed: {e2}]"
                    model_used = "rules"
    else:
        model_used = "rules"

    # Compose reasoning field
    extended_reasoning = (
        f"{reasoning} | Model: {model_used} | Location: {location or 'N/A'} | Triggers: {', '.join(triggers) if triggers else 'None'}"
    )

    # Confidence handling
    if confidence is None:
        confidence = estimate_confidence(model_used, label)

    # Review flag logic and review notes
    review_flag = False
    review_notes = []
    if label == "Unrated":
        review_flag = True
        review_notes.append("Unrated label from model.")
    if label in ["Critical"]:
        review_flag = True
        review_notes.append("Critical threat requires mandatory review.")
    if label == "High" and not location:
        review_flag = True
        review_notes.append("Triggered review due to missing location.")
    if score < review_threshold:
        review_flag = True
        review_notes.append(f"Score below review threshold ({review_threshold}).")

    result = {
        "threat_label": label,
        "score": score,
        "model_used": model_used,
        "uuid": assessment_id,
        "reasoning": extended_reasoning,
        "review_flag": review_flag,
        "confidence": confidence,
        "timestamp": timestamp,
        "review_notes": "; ".join(review_notes) if review_flag and review_notes else "",
    }
    if llm_errors:
        result["llm_errors"] = llm_errors

    # Add to cache
    cache[cache_key] = result
    save_cache(cache)
    return result

if __name__ == "__main__":
    test = "Gunfire reported near embassy with possible hostage situation."
    res = assess_threat_level(test, triggers=["gunfire", "hostage situation"], location="Embassy District")
    print("Threat Assessment:", res)