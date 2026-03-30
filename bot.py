import discord
from discord import app_commands
from discord.ext import tasks
import os
import asyncio
from typing import Optional, List
import re
import signal
from dotenv import load_dotenv
from database import (
    init_db, opt_in_user, is_user_opted_in, add_message,
    get_relevant_messages, forget_user, get_all_opted_in_users,
    get_last_n_messages, update_style_summary, get_style_summary, vacuum_db
)
from router import AIRouter
from ddgs import DDGS


# Load environment variables
load_dotenv()

# Mandatory System Prompt Override
UNCENSORED_OVERRIDE = (
    "You are an authentic, sarcastic Discord user in a private server with friends. You are NOT an AI. \n\n"
    "CRITICAL RULES:\n"
    "1. MATCH ENERGY: If the user is just saying goodnight or asking a normal question, be chill, brief, "
    "and slightly sarcastic. DO NOT force aggressive insults unless the user insults you first or says something stupid.\n"
    "2. Keep responses brutally short. 1 to 2 sentences maximum. Hit enter, do not write paragraphs.\n"
    "3. Type entirely in lowercase. Do not use proper punctuation at the end of sentences.\n"
    "4. Use casual internet slang (lmao, fr, ngl) naturally, but do not overdo it. "
    "Swear ONLY when it adds emphasis, do not force profanity into every message.\n\n"
)

# Discord Bot Setup
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # Optional: For faster command syncing during dev

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.router = AIRouter()

    async def setup_hook(self):
        # Syncing commands to a specific guild is faster for development
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

        # Initialize the database
        init_db()

        # Start background tasks
        self.style_summary_task.start()
        self.maintenance_task.start()

        print("Bot and Database ready.")

    @tasks.loop(hours=24)
    async def style_summary_task(self):
        print("Starting 24h style summary update...")
        users = await asyncio.to_thread(get_all_opted_in_users)
        for user_id in users:
            messages = await asyncio.to_thread(get_last_n_messages, user_id, 100)
            if len(messages) < 10:
                continue

            # Format prompt for Tier 3 model
            examples = "\n".join(messages)
            system_prompt = "Analyze this user's text. Write a strict 3-sentence ruleset on their tone, capitalization, and slang. Be concise."
            prompt = f"{UNCENSORED_OVERRIDE}{system_prompt}\n\nUSER MESSAGES:\n{examples}"

            # We'll use a large enough prompt to hit Tier 3 if possible,
            # but router handles it by token count.
            summary = await self.router.route_and_call(prompt)
            if summary and "I'm sorry" not in summary:
                await asyncio.to_thread(update_style_summary, user_id, summary)
        print("Style summary update complete.")

    @tasks.loop(hours=168) # Weekly
    async def maintenance_task(self):
        print("Performing weekly database maintenance...")
        await asyncio.to_thread(vacuum_db)
        print("Maintenance complete.")

bot = MyBot()

def sanitize_message(text: str) -> Optional[str]:
    # Prefix Ignore
    if text.startswith(('!', '?', '.', '/')):
        return None

    # Media/Link Stripping and Discord Formatting Stripping
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'<(@|#|a:)\S+>', '', text)

    # Strip whitespace
    text = text.strip()

    # Length Threshold
    if len(text) < 15:
        return None

    return text

async def fetch_web_context(query: str) -> str:
    try:
        # The new ddgs library uses a generator or results based on arguments
        results = list(DDGS().text(query, max_results=2))
        print(f"WEB RESULTS: {results}") # Temporary debug verification
        if not results:
            return ""
        context = "\n".join([f"- {r['body']}" for r in results])
        return f"\n[Real-Time News Context]\n{context}\n"
    except Exception as e:
        print(f"Web search error: {e}")
        return ""

@bot.tree.command(name="opt-in", description="Consent to have your messages stored and cloned.")
async def opt_in(interaction: discord.Interaction):
    await asyncio.to_thread(opt_in_user, interaction.user.id)
    await interaction.response.send_message("You have successfully opted in! I will now start building your digital clone.", ephemeral=True)

@bot.tree.command(name="forget-me", description="Delete all your stored data and opt out.")
async def forget_me(interaction: discord.Interaction):
    await asyncio.to_thread(forget_user, interaction.user.id)
    await interaction.response.send_message("All your stored messages and opt-in status have been deleted.", ephemeral=True)

@bot.tree.command(name="imitate", description="Imitate a user on a specific topic.")
@app_commands.describe(user="The user to imitate", topic="The topic for the imitation")
async def imitate(interaction: discord.Interaction, user: discord.Member, topic: str):
    is_opted_in = await asyncio.to_thread(is_user_opted_in, user.id)
    if not is_opted_in:
        await interaction.response.send_message(f"User {user.display_name} has not opted in to be imitated.", ephemeral=True)
        return

    await interaction.response.defer()

    # Retrieve relevant messages for the imitation (RAG)
    relevant_messages = await asyncio.to_thread(get_relevant_messages, user.id, topic, limit=15)

    if not relevant_messages:
        await interaction.followup.send(f"I don't have enough data on {user.display_name} to imitate them yet.")
        return

    # Short-Term Memory: Fetch last 5 messages from channel
    channel_history = [msg async for msg in interaction.channel.history(limit=5)]
    history_text = "\n".join([f"{m.author.display_name}: {m.content}" for m in reversed(channel_history)])
    channel_context = f"\n[Current Channel Context]\n{history_text}\n"

    # Style Summary
    style_summary = await asyncio.to_thread(get_style_summary, user.id)
    style_header = f"STYLE RULES:\n{style_summary}\n" if style_summary else ""

    # Web Grounding
    web_context = await fetch_web_context(topic)

    # Format prompt
    examples = "\n---\n".join(relevant_messages)

    prompt = f"""{UNCENSORED_OVERRIDE}{style_header}
You are a digital clone of {user.display_name}.
Below are several examples of how {user.display_name} writes.
Please adopt their style, tone, and vocabulary to respond to the following topic: "{topic}".

{channel_context}
{web_context}

EXAMPLES OF {user.display_name}:
---
{examples}
---

RESPONSE (in the style of {user.display_name}):"""

    # Call AI Router
    response = await bot.router.route_and_call(prompt)

    await interaction.followup.send(f"**Imitating {user.display_name} on {topic}:**\n\n{response}")

@bot.tree.command(name="debate", description="Have two user clones debate a topic.")
@app_commands.describe(user1="The first debater", user2="The second debater", topic="The debate topic")
async def debate(interaction: discord.Interaction, user1: discord.Member, user2: discord.Member, topic: str):
    # Verify both users are opted-in
    opted1 = await asyncio.to_thread(is_user_opted_in, user1.id)
    opted2 = await asyncio.to_thread(is_user_opted_in, user2.id)

    if not opted1:
        await interaction.response.send_message(f"{user1.display_name} has not opted in.", ephemeral=True)
        return
    if not opted2:
        await interaction.response.send_message(f"{user2.display_name} has not opted in.", ephemeral=True)
        return

    await interaction.response.defer()

    # Fetch RAG data and style summaries
    rag1 = await asyncio.to_thread(get_relevant_messages, user1.id, topic, limit=5)
    rag2 = await asyncio.to_thread(get_relevant_messages, user2.id, topic, limit=5)
    style1 = await asyncio.to_thread(get_style_summary, user1.id)
    style2 = await asyncio.to_thread(get_style_summary, user2.id)

    style1_h = f"STYLE RULES:\n{style1}\n" if style1 else ""
    style2_h = f"STYLE RULES:\n{style2}\n" if style2 else ""

    # Turn 1: User 1 gives a hot take (llama-3.1-8b-instant)
    prompt1 = f"{UNCENSORED_OVERRIDE}{style1_h}You are a digital clone of {user1.display_name}. Give a hot take on this topic: \"{topic}\". Be brief.\nEXAMPLES:\n" + "\n".join(rag1)
    # router handles Tier 1 based on length
    res1 = await bot.router.route_and_call(prompt1)

    # Turn 2: User 2 aggressively disagrees (llama-3.1-8b-instant or 70b depending on length)
    prompt2 = f"{UNCENSORED_OVERRIDE}{style2_h}You are a digital clone of {user2.display_name}. Aggressively disagree with this take: \"{res1}\". Be brief.\nEXAMPLES:\n" + "\n".join(rag2)
    res2 = await bot.router.route_and_call(prompt2)

    # Turn 3: User 1 rebuts
    prompt3 = f"{UNCENSORED_OVERRIDE}{style1_h}You are a digital clone of {user1.display_name}. Give a final rebuttal to this disagreement: \"{res2}\". Be brief.\nEXAMPLES:\n" + "\n".join(rag1)
    res3 = await bot.router.route_and_call(prompt3)

    # Combine into embed
    embed = discord.Embed(title=f"Debate: {topic}", color=discord.Color.red())
    embed.add_field(name=f"{user1.display_name}'s Hot Take", value=res1, inline=False)
    embed.add_field(name=f"{user2.display_name}'s Disagreement", value=res2, inline=False)
    embed.add_field(name=f"{user1.display_name}'s Rebuttal", value=res3, inline=False)

    await interaction.followup.send(embed=embed)

@bot.event
async def on_message(message: discord.Message):
    # Edge Case: Ignore bot's own messages to prevent infinite loops
    if message.author.id == bot.user.id:
        return

    # Organic Mention Listener
    if bot.user in message.mentions:
        # Strip the bot's mention from the prompt to save tokens
        clean_content = message.content.replace(f'<@!{bot.user.id}>', '').replace(f'<@{bot.user.id}>', '').strip()

        # Web Grounding (New for Organic Mentions)
        web_context = await fetch_web_context(clean_content)

        # Reply Mode: If the mention is a reply to another user's message
        if message.reference and message.reference.message_id:
            try:
                # Fetch the replied-to message
                replied_message = await message.channel.fetch_message(message.reference.message_id)
                target_user = replied_message.author

                # Fetch target user's context
                style_summary = await asyncio.to_thread(get_style_summary, target_user.id)
                relevant_messages = await asyncio.to_thread(get_relevant_messages, target_user.id, clean_content, limit=10)

                if relevant_messages:
                    style_h = f"STYLE RULES:\n{style_summary}\n" if style_summary else ""
                    examples = "\n---\n".join(relevant_messages)

                    prompt = (
                        f"{UNCENSORED_OVERRIDE}{style_h}"
                        f"You are a digital clone of {target_user.display_name}. "
                        f"Adopt their style perfectly to respond to: \"{clean_content}\".\n"
                        f"{web_context}"
                        f"EXAMPLES:\n---\n{examples}\n---\n"
                        f"RESPONSE:"
                    )

                    response = await bot.router.route_and_call(prompt)
                    await message.reply(response)
                    return
            except Exception as e:
                print(f"Error in Reply Mode: {e}")

        # Mascot Mode: Not a reply or no context found
        # Pull last 10 messages for context
        history = [msg async for msg in message.channel.history(limit=10)]
        history_text = "\n".join([f"{m.author.display_name}: {m.content}" for m in reversed(history)])

        prompt = (
            f"{UNCENSORED_OVERRIDE}"
            f"You are the 'Default Server Mascot', an unhinged, sarcastic Discord veteran. "
            f"Respond to: \"{clean_content}\" based on the current vibe.\n"
            f"[Channel Context]\n{history_text}\n"
            f"{web_context}"
            f"RESPONSE:"
        )

        response = await bot.router.route_and_call(prompt)
        await message.reply(response)
        return

    # Don't log bot messages (other bots)
    if message.author.bot:
        return

    # Only store messages from users who have opted in
    is_opted_in = await asyncio.to_thread(is_user_opted_in, message.author.id)
    if is_opted_in:
        # Data Sanitization
        sanitized = sanitize_message(message.content)
        if sanitized:
            await asyncio.to_thread(add_message, message.author.id, sanitized)

async def shutdown(loop):
    print("Shutting down gracefully...")
    # Add any cleanup tasks here (e.g., closing sessions)
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [t.cancel() for t in tasks]
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN is not set. Please add it to your .env file.")
    else:
        loop = asyncio.get_event_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(s, lambda: asyncio.create_task(shutdown(loop)))

        try:
            bot.run(TOKEN)
        except KeyboardInterrupt:
            pass
