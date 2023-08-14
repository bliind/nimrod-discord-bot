import discord
import json
import os
import re
import datetime
import nimroddb
from discord import app_commands
from discord.ext import tasks
from time import sleep

class dotdict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

def load_config():
    global config
    config_file = 'config.json' if env == 'prod' else 'config.test.json'
    with open(config_file, encoding='utf8') as stream:
        config = json.load(stream)
    config = dotdict(config)

env = os.getenv('NIMROD_ENV')
load_config()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

######
### Commands
######
@tree.command(name='warn', description='Warn a user', guild=discord.Object(id=config.server))
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    now = datetime.datetime.now()
    if nimroddb.add_warn(interaction.guild.id, user.id, interaction.user.id, int(round(now.timestamp())), reason):
        server = interaction.guild

        userDM = discord.Embed(
            color=discord.Color.yellow(),
            description=f'''
                ## You are receiving a warning from the {server.name} Discord:
                ### {reason}
            '''.replace(' '*16, '').strip()
        )
        userDM.set_author(name=server.name, icon_url=server.icon.url)
        await user.send(embed=userDM)
        await interaction.response.send_message(embed=discord.Embed(description=f'<@{user.id}> warned with reason: `{reason}`'))
    else:
        await interaction.response.send_message("I had a database error, I'm so sorry, please try again")

@tree.command(name='warnings', description='Look up the warnings for a user', guild=discord.Object(id=config.server))
async def warnings(interaction: discord.Interaction, user: discord.Member):
    warnings = nimroddb.list_warns(user.id)
    flag = nimroddb.get_flag(user.id)
    count = len(warnings)
    description = f' '
    for w in warnings:
        w = dotdict(w)
        description += f'''
            **ID: {w.id} | Moderator: <@{w.moderator_id}>**
            {w.reason} - <t:{w.datestamp}:f>
        '''.replace(' '*12, '')
    if flag:
        flag = dotdict(flag)
        description += f'\n\n_Flagged by <@{flag.moderator_id}> on <t:{flag.datestamp}:f>_'
    warnings_embed = discord.Embed(color=discord.Color.yellow(), description=description)
    warnings_embed.set_author(name=f'Warnings for {user.name}{" | " + user.nick if user.nick else ""} ({count})', icon_url=user.display_avatar.url)
    await interaction.response.send_message(embed=warnings_embed)

@tree.command(name='delwarn', description='Delete a warning for a user', guild=discord.Object(id=config.server))
async def delwarn(interaction: discord.Interaction, warn_id: str):
    if nimroddb.del_warn(warn_id):
        await interaction.response.send_message(embed=discord.Embed(description=f'{warn_id} deleted'))
    else:
        await interaction.response.send_message("I had a database error, I'm so sorry, please try again")

@tree.command(name='flag', description='Flag a user as suspicious', guild=discord.Object(id=config.server))
async def flag(interaction: discord.Interaction, user: discord.Member):
    now = datetime.datetime.now()
    if nimroddb.add_flag(config.server, user.id, interaction.user.id, int(round(now.timestamp()))):
        await interaction.response.send_message(embed=discord.Embed(description=f'<@{user.id}> flagged'))
    else:
        await interaction.response.send_message("I had a database error, I'm so sorry, please try again")

@tree.command(name='mute', description='Timeout a user', guild=discord.Object(id=config.server))
async def mute(interaction: discord.Interaction, user: discord.Member, time: str, reason: str):
    match = re.match('(?P<time>\d+)(?P<desig>\w)', time)
    if not match:
        await interaction.response.send_message(f'Unknown time: {time}')
        return

    t = match.group('time')
    desigs = {"d": "days", "h": "hours"}
    try:
        d = desigs[match.group('desig')]
    except:
        await interaction.response.send_message('Only hours or days')
        return

    delta = datetime.timedelta(**{d: int(t)})
    await user.timeout(delta)

    server = [g for g in bot.guilds if g.id == config.server][0]

    userDM = discord.Embed(
        color=discord.Color.red(),
        description=f'''
            ### You have been muted on {server.name} for {round(delta.total_seconds() / 3600)} hours:
            ### {reason}
        '''.replace(' '*12, '').strip()
    )
    userDM.set_thumbnail(url=server.icon.url)
    await user.send(embed=userDM)

    await interaction.response.send_message(embed=discord.Embed(description=f'Timed out <@{user.id}> for `{time}` for `{reason}`'))
    now = datetime.datetime.now()
    try:
        nimroddb.add_warn(config.server, user.id, interaction.user.id, int(round(now.timestamp())), f'(MUTE) {reason}')
    except:
        await interaction.channel.send('Error logging mute to warns')

@tree.command(name='ban', description='Ban a user', guild=discord.Object(id=config.server))
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str, delete_message_days: int=0):
    server = [g for g in bot.guilds if g.id == config.server][0]
    await user.ban(delete_message_days=delete_message_days)

    userDM = discord.Embed(
        color=discord.Color.red(),
        description=f'''
            ### You have been BANNED from {server.name}:
            ### {reason}
        '''.replace(' '*12, '').strip()
    )
    userDM.set_thumbnail(url=server.icon.url)
    await user.send(embed=userDM)
    await interaction.response.send_message(embed=discord.Embed(description=f'Banned <@{user.id}> for `{reason}`'))

######
### Events
######
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=config.server))
    print(f"{config.env.upper()} Nimrod is ready for duty")

bot.run(config.token)
