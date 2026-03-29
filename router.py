import aiohttp
import asyncio
import tiktoken
import os
import time
from typing import List, Dict, Any, Optional

class AIRouter:
    def __init__(self):
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        # For tiktoken, we'll use o200k_base or cl100k_base as a proxy for llama models
        # llama-3.1 models generally use a tiktoken compatible tokenizer (cl100k_base or similar)
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except:
            self.encoding = tiktoken.get_encoding("o200k_base")

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    async def _call_groq(self, session: aiohttp.ClientSession, model: str, prompt: str, retry_count: int = 3) -> Optional[str]:
        if not self.groq_api_key:
            return None

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }

        for attempt in range(retry_count):
            try:
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result["choices"][0]["message"]["content"]
                    elif response.status == 429:
                        wait_time = (2 ** attempt) + 1
                        print(f"Groq Rate Limit (429). Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        print(f"Groq Error ({response.status}): {await response.text()}")
                        return None
            except Exception as e:
                print(f"Groq Exception: {e}")
                return None
        return None

    async def _call_openrouter(self, session: aiohttp.ClientSession, model: str, prompt: str, retry_count: int = 3) -> Optional[str]:
        if not self.openrouter_api_key:
            return None

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jules/doppelganger-bot", # Optional
            "X-Title": "Digital Doppelganger Bot"
        }
        data = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }

        for attempt in range(retry_count):
            try:
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result["choices"][0]["message"]["content"]
                    elif response.status == 429:
                        wait_time = (2 ** attempt) + 1
                        print(f"OpenRouter Rate Limit (429). Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        print(f"OpenRouter Error ({response.status}): {await response.text()}")
                        return None
            except Exception as e:
                print(f"OpenRouter Exception: {e}")
                return None
        return None

    async def route_and_call(self, prompt: str) -> str:
        tokens = self.count_tokens(prompt)
        print(f"Prompt tokens: {tokens}")

        async with aiohttp.ClientSession() as session:
            # Routing logic
            if tokens < 6000:
                print("Routing to Groq (llama-3.1-8b-instant)")
                response = await self._call_groq(session, "llama-3.1-8b-instant", prompt)
            elif 6000 <= tokens < 12000:
                print("Routing to Groq (llama-3.3-70b-versatile)")
                response = await self._call_groq(session, "llama-3.3-70b-versatile", prompt)
            else:
                print("Routing to OpenRouter (xiaomi/mimo-v2-pro)")
                response = await self._call_openrouter(session, "xiaomi/mimo-v2-pro", prompt)

            # Failover to OpenRouter if Groq failed or wasn't available
            if response is None:
                print("Attempting failover to OpenRouter (xiaomi/mimo-v2-pro)")
                response = await self._call_openrouter(session, "xiaomi/mimo-v2-pro", prompt)

            return response or "I'm sorry, I'm having trouble connecting to my brain right now."

if __name__ == "__main__":
    # Mock test
    router = AIRouter()
    print(f"Token count for 'Hello world': {router.count_tokens('Hello world')}")

    # We can't really test the API calls without keys,
    # but we can check the logic by mocking if needed.
    async def test():
        prompt = "Hello, this is a test prompt."
        # result = await router.route_and_call(prompt)
        # print(f"Result: {result}")

    # asyncio.run(test())
