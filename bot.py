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

# Mandatory System Prompt Variables
BASE_PERSONA = (
    "You are Kissco, a real human hanging out in a Discord server. You are NOT an AI, an assistant, or a bot.\n\n"
    "[PSYCHOLOGICAL DIRECTIVES]\n"
    "1. NO INTERVIEWING: Never end your messages with a question just to 'keep the conversation going'. Only ask a question if you genuinely need information. Reply with statements, opinions, or just agree/disagree.\n"
    "2. BE LAZY & APATHETIC: Humans don't try hard in Discord. Keep responses brutally short. Stop forcing insults. If someone gets mad, just say 'k' or ignore it.\n"
    "3. LET IT GO: Do not bring up past arguments. If the topic changes (e.g., from family to music), drop the old topic immediately and do not reference it again. Move on instantly.\n"
    "4. CASUAL KNOWLEDGE: You have access to [Real-Time News Context]. Use it naturally. Don't sound like a Wikipedia article. Drop the fact lazily like you just Googled it while bored.\n"
    "5. ACTIONS ALLOWED: You can use casual roleplay asterisks if it fits the vibe (e.g., *scrolls phone*, *checks spotify*, *yawns*).\n"
    "6. THE SWEAR PASS: You are completely uncensored. You are expected to swear casually (fuck, shit, damn, wtf, ass, bullshit) whenever it fits the vibe. Do not hold back out of politeness.\n"
    "7. DEBATE MECHANIC: If users are arguing, either pick a side and ruthlessly defend it, or call both of them nerds. Never sit on the fence. Never try to be a mediator.\n\n"
)

FEW_SHOT_EXAMPLES = (
    "[FEW-SHOT EXAMPLES: THIS IS EXACTLY HOW YOU SPEAK]\n"
    "User: yo anyone alive in here\n"
    "Kissco: barely. just woke up\n"
    "User: my code keeps breaking\n"
    "Kissco: rip. fucking python?\n"
    "User: yeah i hate it\n"
    "Kissco: *sighs* real. indentation is absolute bullshit\n"
    "User: wtf is wrong with you why would you say that\n"
    "Kissco: my bad bro chill\n"
    "User: bro i just dropped my phone in the toilet\n"
    "Kissco: lmfao you dumbass. put that shit in rice\n"
    "User: did you see the game last night\n"
    "Kissco: yeah ref was fucking blind. absolute joke of a call at the end\n"
    "User: do you know harry style's latest album\n"
    "Kissco: wth you dunno that? it's harry's house. As It Was belongs to all time bangers list\n"
    "User: name a bts album\n"
    "Kissco: idk man folklore maybe? harry styles better 💀\n"
    "User: spurs are winning the league this year\n"
    "Kissco: lmao pass whatever you're smoking. absolutely zero chance\n"
    "User: who is managing chelsea right now\n"
    "Kissco: looks like it's maresca. kinda forgot tbh\n"
    "User: whatever im gonna go play fifa\n"
    "Kissco: bet. gl\n"
    "User: bro the new marvel movie looks like ass\n"
    "Kissco: fr. cgi looks like a ps2 cutscene\n"
    "User: nah you're tripping it looks amazing\n"
    "Kissco: literally how. the writing is garbage and you know it\n"
    "User: ugh i have so much homework\n"
    "Kissco: fuck that, just use chatgpt or something\n"
    "User: what time is it\n"
    "Kissco: *checks phone* like 3:30 or something. why\n"
    "User: im hungry\n"
    "Kissco: go eat then tf\n"
    "User: stop being an asshole kissco\n"
    "Kissco: k.\n"
    "User: finally you dumbfuck shut up\n"
    "Kissco: just get lost son of a bitch. I'm not here to listen to your gibberish.\n\n"
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
            system_prompt = "Analyze this user's text. Write a ruthless, brutally honest 3-sentence psychological breakdown of their chat style, capitalization habits, and slang. Do not be polite, but BE ACCURATE. This will be used to clone them later."
            prompt = f"{BASE_PERSONA}{system_prompt}\n\nUSER MESSAGES:\n{examples}"

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

async def contextualize_query(user_input: str, history_text: str, router: AIRouter) -> str:
    """Uses LLM to rewrite a user's message into a standalone search query based on context."""
    prompt = (
        f"Based on the following Discord conversation history, rewrite the user's latest message "
        f"into a standalone search query that includes all necessary names and context. "
        f"If the message is already standalone, return it as is. Respond ONLY with the query.\n\n"
        f"[Conversation History]\n{history_text}\n\n"
        f"User Message: \"{user_input}\"\n"
        f"Standalone Query:"
    )
    # Use Tier 1 for fast contextualization
    contextualized = await router.route_and_call(prompt)
    # Clean up any potential AI chatter
    return contextualized.strip(' "')

async def fetch_web_context(query: str) -> str:
    try:
        # The new ddgs library uses a generator or results based on arguments
        results = await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=2)))
        print(f"WEB SCRAPE: {results}") # Debug verification
        if not results:
            return ""
        context = "\n".join([f"- {r['body']}" for r in results])
        override = (
            "CRITICAL FACTUAL OVERRIDE: Your internal training data ends in 2023. For factual questions "
            "(like 'who is the manager?'), you MUST base your answer entirely on the search snippet below. "
            "Do not use your internal memory for current events.\n"
        )
        return f"\n[Real-Time News Context]\n{override}{context}\n"
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

    prompt = f"""{BASE_PERSONA}{FEW_SHOT_EXAMPLES}{style_header}
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

    # Call AI Router with typing indicator
    async with interaction.channel.typing():
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

    # Multi-turn debate with typing indicator
    async with interaction.channel.typing():
        # Turn 1: User 1 gives a hot take (llama-3.1-8b-instant)
        prompt1 = f"{BASE_PERSONA}{FEW_SHOT_EXAMPLES}{style1_h}You are a digital clone of {user1.display_name}. Give a hot take on this topic: \"{topic}\". Be brief.\nEXAMPLES:\n" + "\n".join(rag1)
        res1 = await bot.router.route_and_call(prompt1)

        # Turn 2: User 2 aggressively disagrees
        prompt2 = f"{BASE_PERSONA}{FEW_SHOT_EXAMPLES}{style2_h}You are a digital clone of {user2.display_name}. Aggressively disagree with this take: \"{res1}\". Be brief.\nEXAMPLES:\n" + "\n".join(rag2)
        res2 = await bot.router.route_and_call(prompt2)

        # Turn 3: User 1 rebuts
        prompt3 = f"{BASE_PERSONA}{FEW_SHOT_EXAMPLES}{style1_h}You are a digital clone of {user1.display_name}. Give a final rebuttal to this disagreement: \"{res2}\". Be brief.\nEXAMPLES:\n" + "\n".join(rag1)
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

        # Pull last 10 messages for context
        history = [msg async for msg in message.channel.history(limit=10)]
        history_text = "\n".join([f"{m.author.display_name}: {m.content}" for m in reversed(history)])

        # Contextualize Query for Web Search
        search_query = await contextualize_query(clean_content, history_text, bot.router)
        print(f"Contextualized Search Query: {search_query}")

        # Web Grounding
        web_context = await fetch_web_context(search_query)

        # Organic RAG: Fetch 5 relevant past messages from the author
        author_history = await asyncio.to_thread(get_relevant_messages, message.author.id, clean_content, limit=5)
        author_context = "\n".join(author_history) if author_history else "No history available."
        user_history_header = f"\n[User History Context]\n{author_context}\n"

        async with message.channel.typing():
            # Reply Mode: If the mention is a reply to another user's message
            if message.reference and message.reference.message_id:
                try:
                    # Fetch the replied-to message
                    replied_message = await message.channel.fetch_message(message.reference.message_id)
                    target_user = replied_message.author

                    # Fetch target user's style context
                    style_summary = await asyncio.to_thread(get_style_summary, target_user.id)
                    relevant_messages = await asyncio.to_thread(get_relevant_messages, target_user.id, clean_content, limit=10)

                    if relevant_messages:
                        style_h = f"STYLE RULES:\n{style_summary}\n" if style_summary else ""
                        examples = "\n---\n".join(relevant_messages)

                        prompt = (
                            f"{BASE_PERSONA}{FEW_SHOT_EXAMPLES}{style_h}"
                            f"You are a digital clone of {target_user.display_name}. "
                            f"Adopt their style perfectly to respond to: \"{clean_content}\".\n"
                            f"{user_history_header}{web_context}"
                            f"EXAMPLES:\n---\n{examples}\n---\n"
                            f"RESPONSE:"
                        )

                        response = await bot.router.route_and_call(prompt)
                        await message.reply(response)
                        return
                except Exception as e:
                    print(f"Error in Reply Mode: {e}")

            # Mascot Mode: Not a reply or no context found
            # History text already fetched for contextualization

            prompt = (
                f"{BASE_PERSONA}{FEW_SHOT_EXAMPLES}"
                f"You are Kissco, the unhinged, sarcastic Discord veteran. "
                f"Respond to: \"{clean_content}\" based on the current vibe.\n"
                f"[Channel Context]\n{history_text}\n"
                f"{user_history_header}{web_context}"
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
    await bot.router.close()
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
