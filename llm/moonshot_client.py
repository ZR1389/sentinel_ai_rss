"""
Kimi Moonshot API client for Sentinel AI RSS system
Moonshot AI (月之暗面) - cost-effective Chinese AI provider with strong capabilities
"""

import os
import json
import logging
import httpx
from typing import List, Dict, Any, Optional
from monitoring.llm_rate_limiter import rate_limited
from core.config import CONFIG

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("moonshot_client")

# Moonshot API Configuration
MOONSHOT_API_KEY = CONFIG.llm.moonshot_api_key
MOONSHOT_MODEL = CONFIG.llm.moonshot_model
MOONSHOT_BASE_URL = "https://api.moonshot.ai/v1"

@rate_limited("moonshot")
def moonshot_chat(messages: List[Dict[str, str]], temperature: float = 0.4, max_tokens: int = 1000, timeout: float = 20.0) -> Optional[str]:
    """
    Call Kimi Moonshot API for chat completions.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        temperature: Response randomness (0.0-1.0)
        max_tokens: Maximum response length
        timeout: Request timeout in seconds (default: 20s for fast-failover)
        
    Returns:
        Response text or None if failed
    """
    if not MOONSHOT_API_KEY:
        logger.warning("[Moonshot] API key not configured")
        return None
        
    if not messages:
        logger.warning("[Moonshot] No messages provided")
        return None

    try:
        headers = {
            "Authorization": f"Bearer {MOONSHOT_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": MOONSHOT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        logger.debug(f"[Moonshot] Calling API with model {MOONSHOT_MODEL}")
        
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{MOONSHOT_BASE_URL}/chat/completions",
                headers=headers,
                json=payload
            )
            
            if response.status_code == 200:
                result = response.json()
                
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    logger.debug(f"[Moonshot] Success: {len(content)} chars")
                    return content.strip()
                else:
                    logger.error(f"[Moonshot] Unexpected response format: {result}")
                    return None
                    
            elif response.status_code == 401:
                logger.error(f"[Moonshot] Authentication failed - check API key. Response: {response.text}")
                return None
            elif response.status_code == 429:
                logger.warning("[Moonshot] Rate limit exceeded")
                return None
            else:
                logger.error(f"[Moonshot] API error {response.status_code}: {response.text}")
                return None
                
    except httpx.TimeoutException:
        logger.error("[Moonshot] Request timeout")
        return None
    except Exception as e:
        logger.error(f"[Moonshot] Unexpected error: {e}")
        return None

class MoonshotClient:
    """Async Moonshot API client"""
    
    def __init__(self):
        self.api_key = MOONSHOT_API_KEY
        self.base_url = MOONSHOT_BASE_URL
        self.model = MOONSHOT_MODEL
        
    async def acomplete(self, messages: List[Dict[str, str]], model: Optional[str] = None, 
                       temperature: float = 0.4, max_tokens: int = 1000) -> Optional[str]:
        """
        Async chat completion
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model name override
            temperature: Response randomness (0.0-1.0)  
            max_tokens: Maximum response length
            
        Returns:
            Response text or None if failed
        """
        if not self.api_key:
            logger.warning("[Moonshot] API key not configured")
            return None
            
        if not messages:
            logger.warning("[Moonshot] No messages provided")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": model or self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            logger.debug(f"[Moonshot] Calling API with model {model or self.model}")
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result["choices"][0]["message"]["content"]
                    logger.debug(f"[Moonshot] Success: {len(content)} chars")
                    return content
                elif response.status_code == 401:
                    logger.error(f"[Moonshot] Authentication failed - check API key. Response: {response.text}")
                    return None
                elif response.status_code == 429:
                    logger.warning("[Moonshot] Rate limit exceeded")
                    return None
                else:
                    logger.error(f"[Moonshot] API error {response.status_code}: {response.text}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error("[Moonshot] Request timeout")
            return None
        except Exception as e:
            logger.error(f"[Moonshot] Unexpected error: {e}")
            return None

def test_moonshot_connection() -> bool:
    """Test if Moonshot API is working correctly."""
    if not MOONSHOT_API_KEY:
        print("❌ MOONSHOT_API_KEY not configured")
        return False
        
    test_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say 'Hello from Moonshot!' if you can hear me."}
    ]
    
    result = moonshot_chat(test_messages, temperature=0.1)
    
    if result:
        print(f"✅ Moonshot API working: {result}")
        return True
    else:
        print("❌ Moonshot API test failed")
        return False

if __name__ == "__main__":
    # Test the connection when run directly
    test_moonshot_connection()