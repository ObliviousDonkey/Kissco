# Digital Doppelgänger Discord Bot (V1)

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Create a `.env` file with the following variables:
   ```env
   DISCORD_TOKEN=your_discord_bot_token
   GROQ_API_KEY=your_groq_api_key
   GUILD_ID=your_testing_guild_id (optional)
   ```
3. Run the bot:
   ```bash
   python bot.py
   ```

## Features

- `/opt-in`: Consent to have your messages stored and cloned.
- `/imitate [user] [topic]`: Generate a response in the style of a user who has opted in.
- `/debate [user1] [user2] [topic]`: Simulate a debate between two digital clones.
- `/forget-me`: Delete all your stored data and opt out.
- Automatic message logging for opted-in users (messages are only stored if a user has opted in).
- Stateless database layer using SQLite with `sqlite-vec` for semantic search.
- Multi-model routing (Groq Exclusively) based on token counts with independent failover.
- Local embedding generation using `sentence-transformers` (all-MiniLM-L6-v2).
- Short-term memory (last 5 messages) and Web Grounding (DuckDuckGo Search) for context.
- Automatic Style Summarization (updated every 24h).
- Data Sanitization (stripping links/tags, filtering short messages).
- Exponential backoff for rate-limited (429) API calls.

## Tech Stack

- Python 3.12+
- `discord.py` (Slash Commands)
- `sqlite-vec` (Local vector database)
- `sentence-transformers` (Local embeddings)
- `tiktoken` (Local token counting)
- `aiohttp` (Async API calls)
- `Groq` (AI Inference)
