import requests
import hashlib
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()
client = OpenAI()

translation_cache = {}

def translate_snippet(snippet, lang):
    """
    Translates a text snippet into English. Tries LibreTranslate first,
    then falls back to OpenAI.
    """
    key = hashlib.sha256((snippet + lang).encode("utf-8")).hexdigest()
    if key in translation_cache:
        return translation_cache[key]

    # Try LibreTranslate first
    try:
        response = requests.post(
            "https://libretranslate.com/translate",
            data={"q": snippet, "source": lang, "target": "en", "format": "text"},
            timeout=10
        )
        response.raise_for_status()
        translated = response.json().get("translatedText", None)
        if translated:
            translation_cache[key] = translated
            return translated
    except Exception as e:
        print(f"[LibreTranslate error] {e}")

    # Fallback: OpenAI translation
    try:
        system = "Translate the following text to English as accurately as possible."
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": snippet}
            ],
            temperature=0.3
        )
        translated = completion.choices[0].message.content.strip()
        translation_cache[key] = translated
        return translated
    except Exception as e:
        print(f"[OpenAI fallback error] {e}")

    # Final fallback
    translation_cache[key] = snippet
    return snippet
