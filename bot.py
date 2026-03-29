import discord
from discord import app_commands
import os
import asyncio
from dotenv import load_dotenv
from database import init_db, opt_in_user, is_user_opted_in, add_message, get_relevant_messages, forget_user
from router import AIRouter

# Load environment variables
load_dotenv()

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
        print("Bot and Database ready.")

bot = MyBot()

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

    # Retrieve relevant messages for the imitation
    relevant_messages = await asyncio.to_thread(get_relevant_messages, user.id, topic, limit=15)

    if not relevant_messages:
        await interaction.followup.send(f"I don't have enough data on {user.display_name} to imitate them yet.")
        return

    # Format Few-Shot prompt
    # Each message should be separated to provide context.
    examples = "\n---\n".join(relevant_messages)

    prompt = f"""You are a digital clone of {user.display_name}.
Below are several examples of how {user.display_name} writes.
Please adopt their style, tone, and vocabulary to respond to the following topic: "{topic}".

EXAMPLES:
---
{examples}
---

RESPONSE (in the style of {user.display_name}):"""

    # Call AI Router
    response = await bot.router.route_and_call(prompt)

    await interaction.followup.send(f"**Imitating {user.display_name} on {topic}:**\n\n{response}")

@bot.event
async def on_message(message: discord.Message):
    # Don't process our own messages or bot messages
    if message.author.bot:
        return

    # Only store messages from users who have opted in
    # Use asyncio.to_thread for potentially blocking DB/embedding operations
    is_opted_in = await asyncio.to_thread(is_user_opted_in, message.author.id)
    if is_opted_in:
        # We also want to skip commands (slash commands aren't messages anyway,
        # but prefixed commands would be).
        # Standard discord.py slash commands don't trigger on_message for the command itself.
        await asyncio.to_thread(add_message, message.author.id, message.content)

if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN is not set. Please add it to your .env file.")
    else:
        bot.run(TOKEN)
