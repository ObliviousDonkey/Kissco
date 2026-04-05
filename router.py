import aiohttp
import asyncio
import tiktoken
import os
from typing import Optional

class AIRouter:
    def __init__(self):
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.session = None
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.encoding = tiktoken.get_encoding("o200k_base")

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    async def _call_groq(self, session: aiohttp.ClientSession, model: str, prompt: str) -> Optional[str]:
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
                    return "RATE_LIMIT"
                else:
                    print(f"Groq Error ({response.status}) for model {model}")
                    return None
        except Exception as e:
            print(f"Groq Exception for model {model}: {e}")
            return None

    async def route_and_call(self, prompt: str) -> str:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

        tokens = self.count_tokens(prompt)
        print(f"Prompt tokens: {tokens}")

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
        response = await self._call_groq(self.session, model, prompt)

        # Failover logic: if primary model returns 429, wait 1s and retry with backup
        if response == "RATE_LIMIT":
            print("Primary model rate limited. Waiting 1 second for failover...")
            await asyncio.sleep(1)
            backup_model = "openai/gpt-oss-120b"
            print(f"Attempting failover to Groq secondary backup: {backup_model}")
            response = await self._call_groq(self.session, backup_model, prompt)
            if response == "RATE_LIMIT":
                response = None

        return response or "I'm sorry, I'm having trouble connecting to my brain right now."

if __name__ == "__main__":
    router = AIRouter()
    print(f"Token count for 'Hello world': {router.count_tokens('Hello world')}")
#
