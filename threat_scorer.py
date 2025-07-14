import json
import os
from prompts import THREAT_SCORER_SYSTEM_PROMPT
from xai_client import grok_chat
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def assess_threat_level(alert_text, triggers=None, location=None, alert_uuid=None, plan="FREE"):
    """
    Assess the threat level for an alert.
    - Rules-based escalation for certain keywords.
    - LLM-based for VIP plans or ambiguous cases.
    - Returns dict with: label, threat_label, score, confidence, reasoning, model_used
    """
    triggers = triggers or []
    alert_text_lower = alert_text.lower()
    # Fast rules-based escalation
    critical_keywords = [
        "active shooter", "explosion", "suicide bombing", "mass killing"
    ]
    for kw in critical_keywords:
        if kw in alert_text_lower:
            return {
                "label": "Critical",
                "threat_label": "Critical",
                "score": 100,
                "confidence": 1.0,
                "reasoning": f"Keyword '{kw}' matched.",
                "model_used": "rules"
            }
    high_keywords = [
        "armed robbery", "kidnapping", "hostage", "carjacking"
    ]
    for kw in high_keywords:
        if kw in alert_text_lower:
            return {
                "label": "High",
                "threat_label": "High",
                "score": 85,
                "confidence": 0.95,
                "reasoning": f"Keyword '{kw}' matched.",
                "model_used": "rules"
            }

    # LLM-based scoring for VIP or ambiguous cases
    if plan == "VIP" or not triggers:
        prompt = THREAT_SCORER_SYSTEM_PROMPT.format(
            alert_text=alert_text, triggers=triggers, location=location
        )
        messages = [
            {"role": "system", "content": ""},
            {"role": "user", "content": prompt}
        ]
        result = None
        try:
            result = grok_chat(messages, temperature=0.2, max_tokens=100)
            if result:
                data = json.loads(result)
                return {
                    "label": data.get("label", "Unrated"),
                    "threat_label": data.get("label", "Unrated"),
                    "score": data.get("score", 0),
                    "confidence": data.get("confidence", 0.7),
                    "reasoning": data.get("reasoning", ""),
                    "model_used": "grok"
                }
        except Exception as e:
            print(f"[ThreatScorer][Grok] {e}")
        if openai_client:
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=messages,
                    temperature=0.2,
                    max_tokens=100
                )
                reply = response.choices[0].message.content.strip()
                data = json.loads(reply)
                return {
                    "label": data.get("label", "Unrated"),
                    "threat_label": data.get("label", "Unrated"),
                    "score": data.get("score", 0),
                    "confidence": data.get("confidence", 0.7),
                    "reasoning": data.get("reasoning", ""),
                    "model_used": "openai"
                }
            except Exception as e:
                print(f"[ThreatScorer][OpenAI] {e}")

    # Default/fallback
    return {
        "label": "Moderate",
        "threat_label": "Moderate",
        "score": 60,
        "confidence": 0.7,
        "reasoning": "No critical or high keywords, rules fallback.",
        "model_used": "rules"
    }