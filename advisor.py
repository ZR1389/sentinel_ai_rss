import os
from openai import OpenAI
from dotenv import load_dotenv
from plan_rules import PLAN_RULES
from plan_utils import get_plan, PLAN_RULES

load_dotenv()
client = OpenAI()

def generate_advice(user_message, alerts, lang="en", email="anonymous"):
    plan = get_plan(email)
    insight_level = PLAN_RULES.get(plan, {}).get("insights", False)

    # ✅ Return generic message if plan doesn’t allow insights
    if not insight_level or plan == "FREE":
        return (
            "🛡️ Basic safety alert summary:\n"
            "- Monitor your surroundings.\n"
            "- Follow official travel advisories.\n"
            "- Upgrade to receive personalized threat analysis."
        )

    # ✅ Use GPT to generate tailored insight
    try:
        content = f"You are a global security advisor. Based on the following user message and alerts, provide a safety briefing for a traveler:\n\n"
        content += f"User message: {user_message}\n\n"
        content += f"Alerts:\n"
        for alert in alerts[:5]:
            content += f"- {alert['title']}: {alert['summary']}\n"

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
        return f"⚠️ Error generating advisory: {str(e)}"
