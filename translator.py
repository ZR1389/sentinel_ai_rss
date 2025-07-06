from openai import OpenAI
import os
from dotenv import load_dotenv
import signal

load_dotenv()
client = OpenAI()

def timeout_handler(signum, frame):
    raise TimeoutError("OpenAI timed out")

def translate_text(text, target_lang="en"):
    if not text or target_lang.lower() == "en":
        return text  # No translation needed
    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(15)
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"Translate the following into {target_lang}."},
                {"role": "user", "content": text}
            ],
            temperature=0.3,
        )
        signal.alarm(0)
        return response.choices[0].message.content.strip()
    except Exception as e:
        signal.alarm(0)
        print(f"Translation failed: {e}")
        return text  # Return original if translation fails