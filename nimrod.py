import discord
import asyncio
import json
import os
import re
import io
import aiohttp
import datetime
import nimroddb
from discord import app_commands
from discord.ext import tasks

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

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.synced = False
    
    async def on_ready(self):
        if not self.synced:
            await tree.sync(guild=discord.Object(id=config.server))
            self.synced = True
            run_queue.start()

        print(f"{config.env.upper()} Nimrod is ready for duty")

bot = MyClient()
tree = app_commands.CommandTree(bot)

queue = {"Member": [], "New Account": []}
queue_timer = 0

def get_member_image(member):
    try:
        if member.guild_avatar:
            return member.guild_avatar.url
    except: pass
    try:
        if member.display_avatar:
            return member.display_avatar.url
    except: pass
    try:
        return member.avatar.url
    except:
        return None

def get_member_name(member):
    try: 
        if member.nick: return member.nick
    except: pass
    try:
        if member.display_name: return member.display_name
    except: pass
    try:
        if member.global_name: return member.global_name
    except: pass

    return member.name

def make_embed(color, member, description='', **kwargs):
    color = getattr(discord.Color, color)
    embed = discord.Embed(
        color=color(),
        timestamp=datetime.datetime.now(),
        description=description,
        **kwargs
    )

    if not member:
        return None

    if isinstance(member, discord.Member) or isinstance(member, discord.User):
        embed.set_author(name=get_member_name(member), icon_url=get_member_image(member))
        embed.set_thumbnail(url=get_member_image(member))
        embed.set_footer(text=f'User ID: {member.id}')
    elif isinstance(member, discord.Guild):
        embed.set_author(name=member.name, icon_url=member.icon.url)
        embed.set_thumbnail(url=member.icon.url)

    return embed

######
### Commands
######
@tree.command(name='warn', description='Warn a user', guild=discord.Object(id=config.server))
async def warn(interaction: discord.Interaction, user: discord.User, reason: str):
    await interaction.response.defer()
    now = datetime.datetime.now()
    warn_id = await nimroddb.add_warn(interaction.guild.id, user.id, interaction.user.id, int(round(now.timestamp())), reason)
    if warn_id != False:
        server = interaction.guild

        userDM = make_embed('yellow', server, f'### You have been warned on the {server.name} Discord')
        userDM.add_field(name='Warning', value=reason, inline=False)
        try:
            await user.send(embed=userDM)
            dm_sent = True
        except:
            dm_sent = False

        response = make_embed('yellow', user, f'{user.mention} warned')
        response.add_field(name='reason', value=reason, inline=False)
        if not dm_sent:
            response.description += '\n\n_Could not DM user_'
        outgoing = await interaction.followup.send(embed=response)

        await nimroddb.add_warn_message_id(warn_id, outgoing.channel.id, outgoing.id)

        # log
        log_embed = make_embed('red', user, f'<@{user.id}> has been warned by <@{interaction.user.id}>')
        log_embed.add_field(name='reason', value=reason, inline=False)
        log_channel = bot.get_channel(config.mod_logs_channel)
        await log_channel.send(embed=log_embed)
    else:
        await interaction.followup.send("I had a database error, I'm so sorry, please try again")

@tree.command(name='warnings', description='Look up the warnings for a user', guild=discord.Object(id=config.server))
async def warnings(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer()
    warnings = await nimroddb.list_warns(user.id)
    count = len(warnings)
    description = f'Warnings for {user.mention} ({count}):\n'
    for w in warnings:
        w = dotdict(w)
        if w.message_id:
            link = f'https://discord.com/channels/{config.server}/{w.channel_id}/{w.message_id}'
            description += f'\n**ID: [{w.id}]({link}) | Moderator: <@{w.moderator_id}>**'
        else:
            description += f'\n**ID: {w.id} | Moderator: <@{w.moderator_id}>**'
        description += f'\n{w.reason} - <t:{w.datestamp}:f>\n'

    warnings_embed = make_embed('yellow', user, description)
    await interaction.followup.send(embed=warnings_embed)

@tree.command(name='delwarn', description='Delete a warning for a user', guild=discord.Object(id=config.server))
async def delwarn(interaction: discord.Interaction, warn_id: str):
    await interaction.response.defer()
    if await nimroddb.del_warn(warn_id):
        await interaction.followup.send(embed=discord.Embed(timestamp=datetime.datetime.now(), description=f'{warn_id} deleted'))
    else:
        await interaction.followup.send("Something went wrong")

@tree.command(name='flag', description='Flag a user as suspicious', guild=discord.Object(id=config.server))
async def flag(interaction: discord.Interaction, user: discord.User, reason: str):
    await interaction.response.defer()
    now = datetime.datetime.now()
    reason = f'(FLAG) {reason}'
    warn_id = await nimroddb.add_warn(interaction.guild.id, user.id, interaction.user.id, int(round(now.timestamp())), reason)
    if warn_id != False:
        embed = make_embed('yellow', user, f'{user.mention} flagged for: {reason}')
        outgoing = await interaction.followup.send(embed=embed)
        await nimroddb.add_warn_message_id(warn_id, outgoing.channel.id, outgoing.id)
    else:
        await interaction.followup.send(content='I had a database error, I\'m so sorry, please try again')

@tree.command(name='mute', description='Timeout a user', guild=discord.Object(id=config.server))
async def mute(interaction: discord.Interaction, user: discord.User, time: str, reason: str):
    await interaction.response.defer()

    server = interaction.guild
    member = server.get_member(user.id)
    if not member:
        await interaction.followup.send(f'User no longer on the server?')
        return

    match = re.match(r'(?P<time>\d+)(?P<desig>\w)', time)
    if not match:
        await interaction.followup.send(f'Unknown time: {time}')
        return

    t = match.group('time')
    desigs = {"d": "days", "h": "hours"}
    try:
        d = desigs[match.group('desig')]
    except:
        await interaction.followup.send('Only hours or days')
        return

    delta = datetime.timedelta(**{d: int(t)})
    await member.timeout(delta)

    hours = round(delta.total_seconds() / 3600)
    days = int(hours/24)
    remain_hours = int(hours - (days*24))

    user_time = ''
    if days > 0:
        user_time = f'{days} day{"s" if days > 1 else ""} '
    if remain_hours > 0:
        user_time += f'{hours} hour{"s" if hours > 1 else ""}'

    userDM = make_embed('red', server, f'### You have been muted on the {server.name} Discord')
    userDM.add_field(name='Duration', value=user_time, inline=False)
    userDM.add_field(name='Reason', value=reason, inline=False)
    dm_sent = False
    try:
        await user.send(embed=userDM)
        dm_sent = True
    except: pass

    response = make_embed('red', user, f'Timed out <@{user.id}> for {time}')
    response.add_field(name='reason', value=reason, inline=False)
    if not dm_sent:
        response.description += '\n\n_Could not DM user_'
    outgoing = await interaction.followup.send(embed=response)

    # log
    log_embed = make_embed('red', user, f'<@{user.id}> has been timed out for {time} by <@{interaction.user.id}>')
    log_embed.add_field(name='reason', value=reason, inline=False)
    log_channel = bot.get_channel(config.mod_logs_channel)
    await log_channel.send(embed=log_embed)

    now = datetime.datetime.now()
    try:
        warn_id = await nimroddb.add_warn(config.server, user.id, interaction.user.id, int(round(now.timestamp())), f'(MUTE) {reason}')
        await nimroddb.add_warn_message_id(warn_id, outgoing.channel.id, outgoing.id)
    except:
        await interaction.channel.send('Error logging mute to warns')

@tree.command(name='ban', description='Ban a user', guild=discord.Object(id=config.server))
async def ban(interaction: discord.Interaction, user: discord.User, reason: str, delete_message_days: int=0):
    await interaction.response.defer()

    server = interaction.guild

    userDM = make_embed('red', server, f'### You have been banned from the {server.name} Discord')
    userDM.add_field(name='Reason', value=reason)
    dm_sent = False
    try:
        await user.send(embed=userDM)
        dm_sent = True
    except: pass

    await asyncio.sleep(0.5)
    await interaction.guild.ban(user, reason=reason, delete_message_seconds=delete_message_days*86400)

    response = make_embed('red', user, f'Banned <@{user.id}>')
    response.add_field(name='reason', value=reason, inline=False)
    if not dm_sent:
        response.description += '\n\n_Could not DM user_'
    outgoing = await interaction.followup.send(embed=response)

    # log
    log_embed = make_embed('red', user, f'<@{user.id}> has been banned by <@{interaction.user.id}>')
    log_embed.add_field(name='reason', value=reason, inline=False)
    log_channel = bot.get_channel(config.mod_logs_channel)
    await log_channel.send(embed=log_embed)

    now = datetime.datetime.now()
    try:
        warn_id = await nimroddb.add_warn(config.server, user.id, interaction.user.id, int(round(now.timestamp())), f'(BAN) {reason}')
        await nimroddb.add_warn_message_id(warn_id, outgoing.channel.id, outgoing.id)
    except:
        await interaction.channel.send('Error logging ban to warns')

@tree.command(name='appeal', description='Log a Ban Appeal', guild=discord.Object(id=config.server))
async def appeal_command(interaction: discord.Interaction, user: str, decision: str, notes: str=''):
    embed = make_embed('blue', interaction.user, f'### Ban appeal for __{user}__')
    embed.add_field(name='Decision', value=decision, inline=False)
    embed.add_field(name='Notes', value=notes, inline=False)
    await interaction.response.send_message(embed=embed)

######
### Events
######
@bot.event
async def on_raw_member_remove(event):
    member = event.user
    embed = make_embed('red', member, f'<@{member.id}> left.')
    channel = bot.get_channel(config.user_logs_channel)
    await channel.send(embed=embed)

@bot.event
async def on_member_join(member):
    created = round(int(member.created_at.timestamp()))
    description = f'''
        <@{member.id}> joined.

        Account created <t:{created}:f>
        (Roughly <t:{created}:R>)
    '''.replace(' '*8, '').strip()

    embed = make_embed('green', member, description)
    channel = bot.get_channel(config.user_logs_channel)
    await channel.send(embed=embed)

@bot.event
async def on_message_delete(message):
    if message.channel.id in config.no_log_channels:
        return

    if message.channel.type == discord.ChannelType.public_thread:
        if message.channel.parent.id in config.no_log_channels:
            return

    if message.author.bot:
        return

    created = round(int(message.created_at.timestamp()))
    embed = make_embed('red', message.author, f'in <#{message.channel.id}> by <@{message.author.id}>', title='Message deleted')

    content = message.content
    if message.poll:
        content += '\n**poll**'
        content += f'\n_Question_: {message.poll["question"]["text"]}'
        for answer in message.poll['answers']:
            content += f'\n_Answer_: {answer["poll_media"]["text"]}'

    embed.description += f'\n\n**deleted message**\n{content}'
    embed.description += f'\n\n**originally posted**\n<t:{created}:f>'

    if message.reference:
        embed.description += f'\n\n**reply to**\nhttps://discord.com/channels/{config.server}/{message.channel.id}/{message.reference.message_id}'

    files = []
    for file in message.attachments:
        try:
            files.append(await file.to_file(spoiler=file.is_spoiler()))
        except:
            embed.description += '\n_(There were (more?) images attached but discord is stupid)_'

    if files:
        embed.description += '\n_(Above images were attached)_'

    if message.stickers:
        async with aiohttp.ClientSession() as session:
            async with session.get(message.stickers[0].url) as resp:
                if resp.status != 200:
                    print('Failed to download sticker image')
                data = io.BytesIO(await resp.read())
                files.append(discord.File(data, f'{message.stickers[0].name}.png'))
        embed.description += '\n_(Above sticker was attached)_'

    channel = bot.get_channel(config.message_deletes_channel)
    await channel.send(embed=embed, files=files)

@bot.event
async def on_message_edit(before, after):
    if after.channel.id in config.no_log_channels:
        return
    if after.author.bot:
        return

    if before.content.strip() == after.content.strip():
        return

    embed = make_embed(
        color='yellow',
        member=after.author,
        description=f'in <#{after.channel.id}> by <@{after.author.id}>',
        title='Message edited',
        url=after.jump_url
    )
    embed.description += f'\n\n**before**\n{before.content}'
    embed.description += f'\n\n**after**\n{after.content}'
    channel = bot.get_channel(config.message_edits_channel)
    await channel.send(embed=embed)

@bot.event
async def on_member_update(before, after):
    title = f'<@{after.id}> has been updated.\n'
    change_embed = make_embed('blue', after, title)

    if before.nick != after.nick:
        change_embed.description += f'\n🕵️‍♂️ changed nickname from **{before.nick}** to **{after.nick}**'
    
    if before.timed_out_until != after.timed_out_until:
        if before.timed_out_until == None:
            try: timed_out_until = round(int(after.timed_out_until.timestamp()))
            except: timed_out_until = None
            change_embed.description += f'\n⏰ timed out until **<t:{timed_out_until}:f>**'
        if after.timed_out_until == None:
            change_embed.description += f'\n⏰ **timeout removed**'

    if before.guild_avatar != after.guild_avatar:
        change_embed.description += f'\n🖼 updated server avatar\n'

    if change_embed.description != title:
        log_chan = bot.get_channel(config.user_logs_channel)
        await log_chan.send(embed=change_embed)

    role_embed = make_embed('blue', after, title)
    b_roles = [r.name for r in before.roles]
    a_roles = [r.name for r in after.roles]
    added = [r for r in a_roles if r not in b_roles]
    removed = [r for r in b_roles if r not in a_roles]

    global queue
    global queue_timer
    if added:
        if len(added) == 1 and added[0] == 'Member':
            queue['Member'].append(after)
            queue_timer = 10
        else:
            role_embed.description += '\nRoles added:'
            for role_name in added:
                role_embed.description += f'\n✅ {role_name}'

    if removed:
        if len(removed) == 1 and removed[0] == 'New Account':
            queue['New Account'].append(after)
            queue_timer = 10
        else:
            role_embed.description += '\nRoles removed:'
            for role_name in removed:
                role_embed.description += f'\n⛔ {role_name}'

    if role_embed.description != title:
        log_chan = bot.get_channel(config.role_updates_channel)
        await log_chan.send(embed=role_embed)

@bot.event
async def on_member_ban(guild, user):
    embed = make_embed('red', user, f'{user.mention} has been banned.')
    chan = bot.get_channel(config.mod_logs_channel)
    await chan.send(embed=embed)

@bot.event
async def on_member_unban(guild, user):
    embed = make_embed('green', user, f'{user.mention} has been unbanned.')
    chan = bot.get_channel(config.mod_logs_channel)
    await chan.send(embed=embed)

@bot.event
async def on_user_update(before, after):
    pass
    # title = f'<@{after.id}> has been updated.\n'
    # embed = make_embed('blue', after, title)

    # if before.name != after.name:
    #     embed.description += f'\n✏ Changed Username from **{before.name}** to **{after.name}**'

    # if embed.description != title:
    #     log_chan = bot.get_channel(config.user_logs_channel)
    #     await log_chan.send(embed=embed)

@bot.event
async def on_guild_channel_create(channel):
    chan = bot.get_channel(config.server_logs_channel)
    embed = make_embed('green', channel.guild, f'Channel created: <#{channel.id}>')
    await chan.send(embed=embed)

@bot.event
async def on_guild_channel_delete(channel):
    chan = bot.get_channel(config.server_logs_channel)
    embed = make_embed('red', channel.guild, f'Channel deleted: {channel.name} ({channel.id})')
    await chan.send(embed=embed)

@bot.event
async def on_guild_channel_update(before, after):
    overwrites = {}
    befores = {}
    for role in after.changed_roles:
        for ao in after.overwrites_for(role):
            if role.name not in overwrites: overwrites[role.name] = {}
            overwrites[role.name][ao[0]] = ao[1]
        for bo in before.overwrites_for(role):
            if role.name not in befores: befores[role.name] = {}
            befores[role.name][bo[0]] = bo[1]

    final = {}
    description = f'### Channel <#{after.id}> updated:'
    embed = make_embed('blurple', after.guild, description)
    for role, perms in overwrites.items():
        for perm, access in perms.items():
            try: old = befores[role][perm]
            except: old = None
            if old != access:
                final[role] = {}
                final[role][perm] = access

    if len(final.items()):
        embed.description += '\n\n### Permissions Updated:'
    for r, ps in final.items():
        embed.description += f'\n\n:arrow_right: **{r}**'
        for p, a in ps.items():
            emojis = {True: ':white_check_mark:', False: ':no_entry:', None: ':white_large_square:'}
            pr = p.replace('_', ' ').capitalize()
            embed.description += f'\n{emojis[a]} {pr}'

    if before.slowmode_delay != after.slowmode_delay:
        embed.description += f'\n\n### Slowmode updated:\n{before.slowmode_delay} seconds -> {after.slowmode_delay} seconds'

    if embed.description.strip() != description:
        chan = bot.get_channel(config.server_logs_channel)
        await chan.send(embed=embed)

@bot.event
async def on_guild_role_create(role):
    chan = bot.get_channel(config.role_updates_channel)
    embed = make_embed('green', role.guild, f'Role created: {role.mention}')
    await chan.send(embed=embed)

@bot.event
async def on_guild_role_delete(role):
    chan = bot.get_channel(config.role_updates_channel)
    embed = make_embed('red', role.guild, f'Role deleted: {role.name} ({role.id})')
    await chan.send(embed=embed)

@bot.event
async def on_guild_role_update(before, after):
    desc = f'**Role updated: {after.mention}**\n'
    embed = make_embed('blurple', after.guild, desc)
    if before.name != after.name:
        embed.description += f'\n- Name changed from `{before.name}` to `{after.name}`'
    if before.icon != after.icon:
        embed.description += '\n- Role icon changed'
    if after.icon and after.icon.url:
        embed.set_thumbnail(url=after.icon.url)
    if before.color != after.color:
        bc = '#%02x%02x%02x' % before.color.to_rgb()
        ac = '#%02x%02x%02x' % after.color.to_rgb()
        embed.description += f'\n- Color changed from `{bc}` to `{ac}`'

    bp = {}
    changes = {}
    for b in before.permissions:
        bp[b[0]] = b[1]
    for a in after.permissions:
        if bp[a[0]] != a[1]:
            changes[a[0]] = a[1]

    emojis = {True: ':white_check_mark:', False: ':no_entry:', None: ':white_large_square:'}
    if len(changes) > 0:
        embed.description += '\n- Permissions updated:'
        for perm, access in changes.items():
            p = perm.replace('_', ' ').capitalize()
            embed.description += f'\n{emojis[access]} {p}'

    if embed.description != desc:
        chan = bot.get_channel(config.role_updates_channel)
        await chan.send(embed=embed)

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel == after.channel:
        return

    if not before.channel:
        embed = make_embed('blue', member, f'{member.mention} has joined <#{after.channel.id}>')
    elif not after.channel:
        embed = make_embed('dark_red', member, f'{member.mention} has left <#{before.channel.id}>')
    else:
        embed = make_embed('blurple', member, f'{member.mention} switched from <#{before.channel.id}> to <#{after.channel.id}>')

    chan = bot.get_channel(config.voice_logs_channel)
    await chan.send(embed=embed)

### TASKS
@tasks.loop(seconds=10)
async def run_queue():
    global queue
    global queue_timer
    if queue_timer > 0:
        queue_timer = 0
        return
    if len(queue) == 0:
        return

    server = [g for g in bot.guilds if g.id == config.server][0]

    title = '### Member Role Added\n'
    embed = make_embed('blue', server, title)
    for member in queue['Member']:
        embed.description += f'\n✅ {get_member_name(member)} {member.mention}'
    queue['Member'] = []
    if embed.description != title:
        log_chan = bot.get_channel(config.role_updates_channel)
        await log_chan.send(embed=embed)

    title = '### New Account Role Removed\n'
    embed = make_embed('blurple', server, title)
    for member in queue['New Account']:
        embed.description += f'\n⛔ {get_member_name(member)} {member.mention}'
    queue['New Account'] = []
    if embed.description != title:
        log_chan = bot.get_channel(config.role_updates_channel)
        await log_chan.send(embed=embed)

bot.run(config.token)
