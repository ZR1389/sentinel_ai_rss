import os
from openai import OpenAI
from dotenv import load_dotenv
from plan_rules import PLAN_RULES
from plan_utils import get_plan

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=15)

def generate_advice(user_message, alerts, email="anonymous"):
    if not isinstance(user_message, str):
        user_message = str(user_message)

    plan = get_plan(email)
    if not isinstance(plan, str):
        plan = "FREE"

    insight_level = PLAN_RULES.get(plan, {}).get("insights", False)

    if not insight_level or plan.upper() == "FREE":
        return (
            "🛡️ Basic safety alert summary:\n"
            "- Monitor your surroundings.\n"
            "- Follow official travel advisories.\n"
            "- Upgrade to receive personalized threat analysis."
        )

    try:
        content = (
            "You are a global security advisor. Based on the following user message and alerts, provide a clear, practical safety briefing for a traveler:\n\n"
            f"User message: {user_message}\n\n"
            "Alerts:\n"
        )
        for alert in alerts[:5]:
            title = alert.get('title', '')
            summary = alert.get('summary', '')
            content += f"- {str(title)}: {str(summary)}\n"

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Respond as a travel security expert. Be concise, realistic, and actionable."},
                {"role": "user", "content": content}
            ],
            temperature=0.5
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"Error generating advisory: {str(e)}"
