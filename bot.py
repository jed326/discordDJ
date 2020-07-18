import asyncio
import logging
import os
import random
import sys
from collections import deque

import discord
import youtube_dl
from discord.ext import commands

# Set up Logging
log = logging.getLogger()
log.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)

# Setup YT
# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ''
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
}
ffmpeg_options = {
    'options': '-vn'
}
ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


# Set up Bot
token = remote = None
description = '''Plays music in voice channels.
Source: https://github.com/jed326/discordDJ'''
prefix = "!kbot "

if os.environ.get('TOKEN') != None:
    remote = True
    token = os.environ.get('TOKEN')
else:
    token = open("./auth.txt").read()

bot = commands.Bot(command_prefix=prefix, description=description)


@bot.event
async def on_ready():
    log.info("Logged in as bot {} with id {}".format(bot.user.name, bot.user.id))
    log.info("------")

@bot.command()
async def ping(ctx):
    """Ping the bot to check if it's alive."""
    log.info("Received command {} from {}".format(ctx.command, ctx.message.author))
    embed = discord.Embed(title="Title", description="Desc")
    embed.add_field(name="Field1", value="hi", inline=False)
    embed.add_field(name="Field2", value="hi2", inline=False)

    await ctx.send(embed=embed)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.owner = None
        self.queue = deque()
    
    @commands.command()
    async def summon(self, ctx):
        """Summons the bot the user's current voice channel."""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))

        if ctx.author.voice == None:
            await ctx.send("Join a voice channel in order to summon me.")
        else:
            channel = ctx.author.voice.channel
        
        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
    
    @commands.command()
    async def lock(self, ctx):
        """Restricts the bot commands to the current user."""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))

        self.owner = ctx.message.author
        await ctx.send("{} assumed ownership of the bot.".format(self.owner))

    @commands.command()
    async def unlock(self, ctx):
        """Releases the bot lock."""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))

        self.owner = None
        await ctx.send("{} released ownership of the bot.".format(ctx.message.author))

    @commands.command()
    async def add(self, ctx, *, url):
        """Add songs to the play queue."""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))
        
        await self.addToQueue(url)
        await self.sendQueue(ctx)

    # TODO: Error handling
    @commands.command()
    async def play(self, ctx, *, url=None):
        """Plays from a url or the play queue."""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))

        if url is not None:
            await self.addToQueue(url)

        while len(self.queue) > 0:
            current_song = self.queue.pop()[1]
            async with ctx.typing():
                player = await YTDLSource.from_url(current_song, loop=self.bot.loop)
                ctx.voice_client.play(player, after=lambda e: print('Player error: %s' % e) if e else None)

            await ctx.send('Now playing: {}'.format(player.title))
        await ctx.send("No more songs queued.")
    
    @commands.command()
    async def next(self, ctx):
        """Skips to the next song. NYI -- This is really hard to implement for some reason."""
        pass

    @commands.command()
    async def clear(self, ctx):
        """Clears the play queue."""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))
        self.queue = deque()

        await ctx.send("Cleared the play queue")
        await self.sendQueue(ctx)

    @commands.command()
    async def queue(self, ctx):
        """Gets the song queue."""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))

        await self.sendQueue(ctx)


    @commands.command()
    async def pause(self, ctx):
        """Pauses currently playing song."""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))

        if ctx.voice_client.is_playing():
            ctx.voice_client.pause()
        elif ctx.voice_client.is_paused():
            ctx.voice_client.resume()
        else:
            await ctx.send("There is no song currently playing.")
    
    # TODO: volume is not very sensitive. Doesn't seem linear, could be using the API wrong.
    @commands.command()
    async def volume(self, ctx, volume: int):
        """Changes the player's volume"""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))

        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send("Changed volume to {}%".format(volume))

    @commands.command()
    async def stop(self, ctx):
        """Stops and disconnects the bot from voice"""
        log.info("Received command {} from {}".format(ctx.command, ctx.message.author))

        await ctx.voice_client.disconnect()

        dir_name = "."
        for item in os.listdir(dir_name):
            if item.endswith(".webm"):
                os.remove(os.path.join(dir_name, item))
    
    # TODO: it looks like this isn't doing anything
    @play.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("You are not connected to a voice channel.")
                raise commands.CommandError("Author not connected to a voice channel.")
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()

    @summon.before_invoke
    @lock.before_invoke
    @unlock.before_invoke
    @add.before_invoke
    @play.before_invoke
    @pause.before_invoke
    @volume.before_invoke
    @stop.before_invoke
    async def checkLock(self, ctx):
        """Check if the current user is the owner"""
        if not (self.owner == ctx.message.author or self.owner == None):
            await ctx.send("{} is the current bot owner. {} does not have permission to run bot commands.".format(self.owner, ctx.message.author))
            raise commands.CommandError("{} does not have permission to run bot commands".format(ctx.message.author))
    
    async def sendQueue(self, ctx):
        if len(self.queue) == 0:
            return await ctx.send("There are no songs in the play queue")
        else:
            desc = ""
            for item in list(self.queue):
                desc += "* " + item[0] + "\n"
            embed = discord.Embed(title="Play Queue", description=desc)
            await ctx.send(embed=embed)
    
    async def addToQueue(self, url):
        player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
        title = player.title
        del player
        self.queue.appendleft((title, url))



bot.add_cog(Music(bot))
bot.run(token)
