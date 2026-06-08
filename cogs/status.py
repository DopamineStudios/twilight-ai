import discord
from discord.ext import commands

class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        activity = discord.Streaming(
            name="✨ Listening to DMs and @ Mentions",
            url="https://www.twitch.tv/dopaminediscordbot"
        )
        await self.bot.change_presence(activity=activity)

async def setup(bot):
    await bot.add_cog(StatusCog(bot))