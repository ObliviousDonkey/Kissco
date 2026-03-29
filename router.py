import aiohttp
import asyncio
import tiktoken
import os
import time
from typing import List, Dict, Any, Optional

class AIRouter:
    def __init__(self):
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        # For tiktoken, we'll use cl100k_base or o200k_base as a proxy for llama models
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except:
            self.encoding = tiktoken.get_encoding("o200k_base")

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    async def _call_groq(self, session: aiohttp.ClientSession, model: str, prompt: str, retry_on_429: bool = True) -> Optional[str]:
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

        try:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return result["choices"][0]["message"]["content"]
                elif response.status == 429:
                    print(f"Groq Rate Limit (429) for model {model}.")
                    if retry_on_429:
                        # Exponential backoff for first retry
                        wait_time = 2
                        print(f"Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        # Recursive call once with retry_on_429=False
                        return await self._call_groq(session, model, prompt, retry_on_429=False)
                    else:
                        return None
                else:
                    print(f"Groq Error ({response.status}) for model {model}: {await response.text()}")
                    return None
        except Exception as e:
            print(f"Groq Exception for model {model}: {e}")
            return None

    async def route_and_call(self, prompt: str) -> str:
        tokens = self.count_tokens(prompt)
        print(f"Prompt tokens: {tokens}")

        async with aiohttp.ClientSession() as session:
            # Routing logic based on tiered free plan
            if tokens < 6000:
                # Tier 1 (Small): llama-3.1-8b-instant
                model = "llama-3.1-8b-instant"
            elif 6000 <= tokens < 12000:
                # Tier 2 (Medium): llama-3.3-70b-versatile
                model = "llama-3.3-70b-versatile"
            else:
                # Tier 3 (Large/Context): meta-llama/llama-4-scout-17b-16e-instruct
                model = "meta-llama/llama-4-scout-17b-16e-instruct"

            print(f"Routing to Groq primary model: {model}")
            response = await self._call_groq(session, model, prompt)

            # Failover loop: if primary model fails (including 429), attempt secondary backup
            if response is None:
                backup_model = "openai/gpt-oss-120b"
                print(f"Primary model failed. Attempting failover to Groq secondary backup: {backup_model}")
                response = await self._call_groq(session, backup_model, prompt)

            return response or "I'm sorry, I'm having trouble connecting to my brain right now."

if __name__ == "__main__":
    # Mock test
    router = AIRouter()
    print(f"Token count for 'Hello world': {router.count_tokens('Hello world')}")
