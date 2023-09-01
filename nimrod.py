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

        print(f"{config.env.upper()} Nimrod is ready for duty")

bot = MyClient()
tree = app_commands.CommandTree(bot)

def get_member_image(member):
    if member.guild_avatar:
        return member.guild_avatar.url
    if member.display_avatar:
        return member.display_avatar.url
    return member.avatar.url

def get_member_name(member):
    if member.nick:
        return member.nick
    if member.display_name:
        return member.display_name
    return member.name

def make_embed(color, member, description=''):
    color = getattr(discord.Color, color)
    embed = discord.Embed(
        color=color(),
        timestamp=datetime.datetime.now(),
        description=description
    )

    if not member:
        return None

    if isinstance(member, discord.Member):
        embed.set_author(name=get_member_name(member), icon_url=get_member_image(member))
        embed.set_thumbnail(url=get_member_image(member))
    elif isinstance(member, discord.Guild):
        embed.set_author(name=member.name, icon_url=member.icon.url)

    return embed

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
            timestamp=datetime.datetime.now(),
            description=f'''
                ## You are receiving a warning from the {server.name} Discord:
                ### {reason}
            '''.replace(' '*16, '').strip()
        )
        userDM.set_author(name=server.name, icon_url=server.icon.url)
        try:
            await user.send(embed=userDM)
            dm_sent = True
        except:
            dm_sent = False

        warnEmbed = discord.Embed(
            color=discord.Color.yellow(),
            timestamp=datetime.datetime.now(),
            description=f'<@{user.id}> warned with reason: `{reason}`'
        )
        if not dm_sent:
            warnEmbed.description += '\n\n_Could not DM user_'

        warnEmbed.set_author(name=get_member_name(user), icon_url=get_member_image(user))
        await interaction.response.send_message(embed=warnEmbed)

        # log
        log_embed = discord.Embed(
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(),
            description=f'''
                <@{user.id}> has been warned by <@{interaction.user.id}>
                ```{reason}```
            '''.replace(' '*12, '').strip()
        )
        log_embed.set_author(name=get_member_name(user), icon_url=get_member_image(user))
        log_channel = bot.get_channel(config.mod_logs_channel)
        await log_channel.send(embed=log_embed)
    else:
        await interaction.response.send_message("I had a database error, I'm so sorry, please try again")

@tree.command(name='warnings', description='Look up the warnings for a user', guild=discord.Object(id=config.server))
async def warnings(interaction: discord.Interaction, user: discord.Member):
    warnings = nimroddb.list_warns(user.id)
    flag = nimroddb.get_flag(user.id)
    count = len(warnings)
    description = f'{user.mention}\n\n'
    for w in warnings:
        w = dotdict(w)
        description += f'''
            **ID: {w.id} | Moderator: <@{w.moderator_id}>**
            {w.reason} - <t:{w.datestamp}:f>
        '''.replace(' '*12, '')
    if flag:
        flag = dotdict(flag)
        description += f'\n\n_Flagged by <@{flag.moderator_id}> on <t:{flag.datestamp}:f>_'
    warnings_embed = discord.Embed(color=discord.Color.yellow(), timestamp=datetime.datetime.now(), description=description)
    warnings_embed.set_author(name=f'Warnings for {user.name}{" | " + user.nick if user.nick else ""} ({count})', icon_url=get_member_image(user))
    await interaction.response.send_message(embed=warnings_embed)

@tree.command(name='delwarn', description='Delete a warning for a user', guild=discord.Object(id=config.server))
async def delwarn(interaction: discord.Interaction, warn_id: str):
    if nimroddb.del_warn(warn_id):
        await interaction.response.send_message(embed=discord.Embed(timestamp=datetime.datetime.now(), description=f'{warn_id} deleted'))
    else:
        await interaction.response.send_message("Something went wrong")

@tree.command(name='flag', description='Flag a user as suspicious', guild=discord.Object(id=config.server))
async def flag(interaction: discord.Interaction, user: discord.Member):
    now = datetime.datetime.now()
    if nimroddb.add_flag(config.server, user.id, interaction.user.id, int(round(now.timestamp()))):
        em = discord.Embed(
            color=discord.Color.yellow(),
            timestamp=datetime.datetime.now(),
            description=f'<@{user.id}> flagged'
        )
        em.set_author(name=get_member_name(user), icon_url=get_member_image(user))
        await interaction.response.send_message(embed=em)
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
        timestamp=datetime.datetime.now(),
        description=f'''
            ### You have been muted on {server.name} for {round(delta.total_seconds() / 3600)} hours:
            ### {reason}
        '''.replace(' '*12, '').strip()
    )
    userDM.set_thumbnail(url=server.icon.url)
    try:
        await user.send(embed=userDM)
        dm_sent = True
    except:
        dm_sent = False

    response = discord.Embed(
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(),
        description=f'Timed out <@{user.id}> for `{time}` for `{reason}`'
    )
    if not dm_sent:
        response.description += '\n\n_Could not DM user_'
    await interaction.response.send_message(embed=response)

    # log
    log_embed = discord.Embed(
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(),
        description=f'''
            <@{user.id}> has been timed out for {time} by <@{interaction.user.id}>
            ```{reason}```
        '''.replace(' '*12, '').strip()
    )
    log_embed.set_author(name=get_member_name(user), icon_url=get_member_image(user))
    log_channel = bot.get_channel(config.mod_logs_channel)
    await log_channel.send(embed=log_embed)

    now = datetime.datetime.now()
    try:
        nimroddb.add_warn(config.server, user.id, interaction.user.id, int(round(now.timestamp())), f'(MUTE) {reason}')
    except:
        await interaction.channel.send('Error logging mute to warns')

@tree.command(name='ban', description='Ban a user', guild=discord.Object(id=config.server))
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str, delete_message_days: int=0):
    server = [g for g in bot.guilds if g.id == config.server][0]

    userDM = discord.Embed(
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(),
        description=f'''
            ### You have been banned from the {server.name} Discord:
            ### {reason}
        '''.replace(' '*12, '').strip()
    )
    userDM.set_thumbnail(url=server.icon.url)
    dm_sent = False
    try:
        await user.send(embed=userDM)
        dm_sent = True
    except:
        pass

    sleep(0.5)
    await user.ban(delete_message_days=delete_message_days)

    response = discord.Embed(
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(),
        description=f'Banned <@{user.id}> for `{reason}`'
    )
    if not dm_sent:
        response.description += '\n\n_Could not DM user_'
    await interaction.response.send_message(embed=response)

    # log
    log_embed = discord.Embed(
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(),
        description=f'''
            <@{user.id}> has been banned by <@{interaction.user.id}>
            ```{reason}```
        '''.replace(' '*12, '').strip()
    )
    log_embed.set_author(name=get_member_name(user), icon_url=get_member_image(user))
    log_channel = bot.get_channel(config.mod_logs_channel)
    await log_channel.send(embed=log_embed)

######
### Events
######
@bot.event
async def on_raw_member_remove(event):
    member = event.user
    embed = discord.Embed(
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(),
        description=f'<@{member.id}> left.'
    )
    embed.set_author(name=get_member_name(member), icon_url=get_member_image(member))
    embed.set_thumbnail(url=get_member_image(member))

    channel = bot.get_channel(config.user_logs_channel)
    await channel.send(embed=embed)

@bot.event
async def on_member_join(member):
    created = round(int(member.created_at.timestamp()))
    # embed = discord.Embed(
    #     color=discord.Color.green(),
    #     timestamp=datetime.datetime.now(),
    #     description=f'''
    #         <@{member.id}> joined.

    #         Account created <t:{created}:f>
    #         (Roughly <t:{created}:R>)
    #     '''.replace(' '*12, '').strip()
    # )
    # embed.set_author(name=get_member_name(member), icon_url=get_member_image(member))
    # embed.set_thumbnail(url=member.avatar.url)

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
    created = round(int(message.created_at.timestamp()))
    embed = make_embed('red', message.author, 'Message deleted')
    embed.description += f'''
        in <#{message.channel.id}> by <@{message.author.id}>:
        {'```'+message.content+'```' if message.content else ''}

        _originally posted <t:{created}:f>_'''.replace(' '*8, '')

    files = []
    for file in message.attachments:
        files.append(await file.to_file())

    if files:
        embed.description += '\n_(Above images were attached)_'

    channel = bot.get_channel(config.message_deletes_channel)
    await channel.send(embed=embed, files=files)

@bot.event
async def on_message_edit(before, after):
    if before.author.id == bot.user.id:
        return

    embed = make_embed('yellow', after.author, 'Message edited')
    embed.description += f'''
        [Jump to Message]({after.jump_url})
        in <#{after.channel.id}> by <@{after.author.id}>:

        _before:_
        ```{before.content}```
        _after:_
        ```{after.content}```'''.replace(' '*8, '')

    embed.set_author(name=get_member_name(after.author), icon_url=get_member_image(after.author))

    channel = bot.get_channel(config.message_edits_channel)
    await channel.send(embed=embed)

@bot.event
async def on_member_update(before, after):
    title = f'<@{after.id}> has been updated.\n'
    change_embed = make_embed('blue', after, title)

    if before.nick != after.nick:
        change_embed.description += f'\n🕵️‍♂️ changed nickname from **{before.nick}** to **{after.nick}**'
    
    if before.timed_out_until != after.timed_out_until:
        change_embed.description += f'\n⏰ timed out until **<t:{round(int(after.timed_out_until.timestamp()))}:f>**'

    if before.guild_avatar != after.guild_avatar:
        change_embed.description += f'\n🖼 updated server avatar\n'

    if change_embed.description != title:
        log_chan = bot.get_channel(config.user_logs_channel)
        await log_chan.send(embed=change_embed)

    role_embed = make_embed('blue', after, title)
    b_roles = [r.name for r in before.roles]
    a_roles = [r.name for r in after.roles]
    added = [r for r in a_roles if r not in b_roles]
    if added:
        role_embed.description += '\nRoles added:'
        for role_name in added:
            role_embed.description += f'\n✅ {role_name}'

    removed = [r for r in b_roles if r not in a_roles]
    if removed:
        role_embed.description += '\nRoles removed:'
        for role_name in removed:
            role_embed.description += f'\n⛔ {role_name}'

    if role_embed.description != title:
        log_chan = bot.get_channel(config.role_updates_channel)
        role_embed.set_author(name=get_member_name(after), icon_url=get_member_image(after))
        role_embed.set_thumbnail(url=get_member_image(after))
        await log_chan.send(embed=role_embed)

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
    description = f'Permissions updated for <#{after.id}>:'
    embed = make_embed('blurple', after.guild, description)
    for role, perms in overwrites.items():
        final[role] = {}
        for perm, access in perms.items():
            try: old = befores[role][perm]
            except: old = None
            if old != access:
                final[role][perm] = access

    for r, ps in final.items():
        if len(ps) > 0:
            embed.description += f'\n\n:arrow_right: **{r}**'
        for p, a in ps.items():
            emojis = {True: ':white_check_mark:', False: ':no_entry:', None: ':white_large_square:'}
            pr = p.replace('_', ' ').capitalize()
            embed.description += f'\n{emojis[a]} {pr}'

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

bot.run(config.token)
