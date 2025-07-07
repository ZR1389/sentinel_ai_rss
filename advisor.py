import os
from openai import OpenAI
from dotenv import load_dotenv
from plan_rules import PLAN_RULES
from plan_utils import get_plan, PLAN_RULES

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=15)  # Set timeout here

def generate_advice(user_message, alerts, lang="en", email="anonymous"):
    plan = get_plan(email)
    # Make sure plan is a string for comparison
    if not isinstance(plan, str):
        plan = "FREE"
    insight_level = PLAN_RULES.get(plan, {}).get("insights", False)

    # Ensure lang is a string for system prompt
    if not isinstance(lang, str):
        lang = "en"

    # Return generic message if plan doesn’t allow insights
    if not insight_level or (isinstance(plan, str) and plan.upper() == "FREE"):
        return (
            "🛡️ Basic safety alert summary:\n"
            "- Monitor your surroundings.\n"
            "- Follow official travel advisories.\n"
            "- Upgrade to receive personalized threat analysis."
        )

    # Use GPT to generate tailored insight
    try:
        content = (
            "You are a global security advisor. Based on the following user message and alerts, provide a safety briefing for a traveler:\n\n"
            f"User message: {user_message}\n\n"
            "Alerts:\n"
        )
        for alert in alerts[:5]:
            title = alert.get('title', '')
            summary = alert.get('summary', '')
            # Safeguard against dicts/non-strings
            if not isinstance(title, str):
                title = str(title)
            if not isinstance(summary, str):
                summary = str(summary)
            content += f"- {title}: {summary}\n"

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"Respond in {lang}. Use clear, practical language."},
                {"role": "user", "content": content}
            ],
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error generating advisory: {str(e)}"