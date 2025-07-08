import os
from xai_sdk import Client
from xai_sdk.chat import user, system

XAI_API_KEY = os.getenv("GROK_API_KEY")
XAI_API_HOST = "api.x.ai"
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
TEMPERATURE = float(os.getenv("GROK_TEMPERATURE", 0.3))

def grok_chat(messages, model=GROK_MODEL, temperature=TEMPERATURE, max_tokens=300):
    if not XAI_API_KEY:
        print("[Grok-3-mini] API key missing.")
        return None
    try:
        client = Client(api_host=XAI_API_HOST, api_key=XAI_API_KEY)
        chat = client.chat.create(model=model, temperature=temperature)
        for m in messages:
            if m["role"] == "system":
                chat.append(system(m["content"]))
            elif m["role"] == "user":
                chat.append(user(m["content"]))
        response = chat.sample(max_tokens=max_tokens)
        return response.content.strip()
    except Exception as e:
        print(f"[Grok-3-mini error] {e}")
        return None