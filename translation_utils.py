import requests
from googletrans import Translator
import hashlib

translator = Translator()
translation_cache = {}

def translate_snippet(snippet, lang):
    """
    Translates a text snippet into English, using LibreTranslate first, then falling back to googletrans.
    Returns the translated string or the original snippet if both fail.
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
    # Fallback to googletrans
    try:
        result = translator.translate(snippet, src=lang, dest='en')
        translated = result.text
        translation_cache[key] = translated
        return translated
    except Exception as e:
        print(f"[googletrans error] {e}")
    # Final fallback: return original
    translation_cache[key] = snippet
    return snippet