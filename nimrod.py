import discord
import asyncio
import json
import os
import re
import io
import aiohttp
import datetime
import nimroddb
from collections import defaultdict
from discord import app_commands
from discord.ext import tasks
from ReportView import ReportView

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
@tree.command(name='reload_config', description='Reload the bot config', guild=discord.Object(id=config.server))
async def reload_config_command(interaction):
    load_config()
    await interaction.response.send_message('Reloaded', ephemeral=True)

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

@tree.command(name='spam_ban', description='Ban a compromised account', guild=discord.Object(id=config.server))
async def spam_ban(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer()

    server = interaction.guild
    reason = 'Your account has been compromised and is sending spam/scam messages. Once you have secured access to your account please feel free to appeal using https://appeal.gg/marvelsnap'
    userDM = make_embed('red', server, f'### You have been banned from the {server.name} Discord')
    userDM.add_field(name='Reason', value=reason)
    dm_sent = False
    try:
        await user.send(embed=userDM)
        dm_sent = True
    except: pass

    await asyncio.sleep(0.5)
    await interaction.guild.ban(user, reason=reason, delete_message_seconds=86400)

    response = make_embed('red', user, f'Banned <@{user.id}>')
    response.add_field(name='reason', value=reason, inline=False)
    if not dm_sent:
        response.description += '\n\n_Could not DM user_'
    outgoing = await interaction.followup.send(embed=response)

    # log
    log_embed = make_embed('red', user, f'<@{user.id}> has been banned by <@{interaction.user.id}>')
    log_embed.add_field(name='reason', value='Compromised Account', inline=False)
    log_channel = bot.get_channel(config.mod_logs_channel)
    await log_channel.send(embed=log_embed)

    now = datetime.datetime.now()
    try:
        warn_id = await nimroddb.add_warn(config.server, user.id, interaction.user.id, int(round(now.timestamp())), f'(BAN) {reason}')
        await nimroddb.add_warn_message_id(warn_id, outgoing.channel.id, outgoing.id)
    except:
        await interaction.channel.send('Error logging ban to warns')

@tree.command(name='forum_ban', description='Restrict a member from posting to the forums', guild=discord.Object(id=config.server))
async def forum_ban(interaction: discord.Interaction, user: discord.User, reason: str):
    await interaction.response.defer()

    for forum in config.forum_ban_channels:
        forum_chan = bot.get_channel(forum)
        overwrites = forum_chan.overwrites
        overwrites[user] = discord.PermissionOverwrite(view_channel=False, add_reactions=False, send_messages=False, send_messages_in_threads=False)
        await forum_chan.edit(overwrites=overwrites)

    response = make_embed('orange', user, f'<@{user.id}> has been forum banned')
    response.add_field(name='reason', value=reason, inline=False)
    await interaction.followup.send(embed=response)

    # log
    log_embed = make_embed('red', user, f'<@{user.id}> has been forum banned by <@{interaction.user.id}>')
    log_embed.add_field(name='reason', value=reason, inline=False)
    log_channel = bot.get_channel(config.mod_logs_channel)
    await log_channel.send(embed=log_embed)

    try:
        now = datetime.datetime.now()
        await nimroddb.add_warn(config.server, user.id, interaction.user.id, int(round(now.timestamp())), f'(FORUM BAN) {reason}')
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
# scam spam prevention
spam_tracker = defaultdict(list)
currently_flagged_users = set()

async def clean_expired_signatures(user_id: int):
    await asyncio.sleep(config.spam_time_window)
    if user_id in currently_flagged_users:
        return

    if user_id in spam_tracker:
        now = datetime.datetime.now(datetime.timezone.utc)
        valid_start = now - datetime.timedelta(seconds=config.spam_time_window)

        spam_tracker[user_id] = [
            item for item in spam_tracker[user_id] if item[1] > valid_start
        ]

        if not spam_tracker[user_id]:
            del spam_tracker[user_id]

async def flag_and_mute(user_id: int, guild: discord.Guild, target_signature: str):
    await asyncio.sleep(2)

    member = guild.get_member(user_id)
    if not member:
        currently_flagged_users.discard(user_id)
        spam_tracker.pop(user_id, None)
        return

    cached_msgs = spam_tracker.get(user_id, [])
    messages_to_delete = [
        msg for sig, _, msg in cached_msgs if sig == target_signature
    ]

    spam_tracker.pop(user_id, None)
    currently_flagged_users.discard(user_id)

    preserved_files = []
    if messages_to_delete:
        sample_msg = messages_to_delete[0]
        for img in [a for a in sample_msg.attachments if a.width is not None]:
            try:
                img_bytes = await img.read()
                preserved_files.append(
                    discord.File(io.BytesIO(img_bytes), filename=img.filename)
                )
            except Exception as e:
                print(f'Failed to preserve attachment byte sequence: {e}')

    try:
        await member.timeout(
            datetime.timedelta(minutes=10),
            reason='Automated Spam Detection'
        )
    except discord.Forbidden:
        print(f'Bot cannot mute {member.name}')

    channels_hit = set()
    for msg in messages_to_delete:
        channels_hit.add(msg.channel.mention)
        try:
            await msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        except Exception as e:
            print(f'Could not delete message: {e}')

    log_channel = discord.utils.get(guild.text_channels, id=config.report_channel)
    mod_role = discord.utils.get(guild.roles, id=config.moderator_role)

    report_view = ReportView(timeout=None)
    if log_channel:
        channels_str = ', '.join(channels_hit)
        title = 'Automated Spam Detection'
        description = f'**User**\n{member.mention} ({member.id})\n\n' \
                    f'**Channels cleaned**:\n{channels_str}\n\n' \
                    'Attached images were spammed. User is under 10m timeout.'
        embed = make_embed('yellow', member, description, title=title)

        report_message = await log_channel.send(content=f'{mod_role.mention if mod_role else ""}', embed=embed, files=preserved_files, view=report_view)
        await report_view.wait()
        if report_view.value:
            u = report_view.buttonpusher

            userDM = make_embed('red', guild, f'### You have been banned from the {guild.name} Discord')
            userDM.add_field(name='Reason', value='Your account has been compromised and is sending spam/scam messages. Once you have secured access to your account please feel free to appeal using https://appeal.gg/marvelsnap')
            try:
                await member.send(embed=userDM)
            except Exception:
                pass
            await asyncio.sleep(0.5)
            await guild.ban(member, reason='Compromised account', delete_message_seconds=86400)

            embed.description += f'\n\n✅ Banned by {u.mention} ({u.name})'
            embed.color = discord.Color.green()
        elif report_view.value == False:
            u = report_view.buttonpusher

            await member.timeout(None)
            await log_channel.send('<@145971157902950401> there was a false positive')
            embed.description += f'\n\n❌ {u.mention} ({u.name}) marked this a false report'
            embed.color = discord.Color.red()
        await report_message.edit(embed=embed, view=report_view)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    valid_images = [a for a in message.attachments if a.width is not None]
    if len(valid_images) != 4:
        return

    meta_elements = [f'{img.filename}_{img.size}' for img in valid_images]
    meta_elements.sort()
    payload_signature = '|'.join(meta_elements)

    user_id = message.author.id
    now = datetime.datetime.now(datetime.timezone.utc)

    if user_id in currently_flagged_users:
        # if already flagged just log
        spam_tracker[user_id].append((payload_signature, now, message))
        return

    recent_signatures = [item[0] for item in spam_tracker[user_id]]
    if payload_signature in recent_signatures and len(recent_signatures) > 1:
        # same 4 images send to at least 3 channels, flag em
        currently_flagged_users.add(user_id)
        spam_tracker[user_id].append((payload_signature, now, message))

        asyncio.create_task(flag_and_mute(user_id, message.guild, payload_signature))
        return

    spam_tracker[user_id].append((payload_signature, now, message))
    asyncio.create_task(clean_expired_signatures(user_id))

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
async def on_message_delete(message, thread=False, bulk=False):
    if message.channel.id in config.no_log_channels:
        return
    if message.channel.type in [discord.ChannelType.public_thread, discord.ChannelType.private_thread]:
        if message.channel.parent.id in config.no_log_channels:
            return
    if message.author.bot:
        return

    created = round(int(message.created_at.timestamp()))
    title = 'Message deleted'
    if bulk == True:
        title = 'Messages bulk deleted'

    description = f'in <#{message.channel.id}> by <@{message.author.id}>'
    if thread == True:
        title = 'Thread deleted'
        description = f'"{message.channel.name}" in <#{message.channel.parent.id}> by <@{message.author.id}>'

    embed = make_embed('red', message.author, description, title=title)

    content = message.content
    if message.poll:
        content += '\n**poll**'
        content += f'\n_Question_: {message.poll["question"]["text"]}'
        for answer in message.poll['answers']:
            content += f'\n_Answer_: {answer["poll_media"]["text"]}'

    embed.description += f'\n\n**deleted message**\n{content}'
    embed.description += f'\n\n**originally posted**\n<t:{created}:f>'
    embed.description += f'\n\n**message id**\n{message.id}'

    if message.reference:
        embed.description += f'\n\n**reply to**\nhttps://discord.com/channels/{config.server}/{message.channel.id}/{message.reference.message_id}'

    files = []
    try:
        for file in message.attachments:
            async with aiohttp.ClientSession() as session:
                async with session.get(file.url) as resp:
                    if resp.status != 200:
                        raise Exception
                    data = io.BytesIO(await resp.read())
                    files.append(discord.File(data, f'{file.filename}'))
    except Exception:
        embed.description += f'\n_(There were {len(message.attachments)} images attached but discord is stupid)_'

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
async def on_thread_delete(thread):
    try: await on_message_delete(thread.starter_message, thread=True)
    except Exception as e:
        print('Failed to log thread deletion')
        print(e)

@bot.event
async def on_bulk_message_delete(messages):
    for message in messages:
        await on_message_delete(message, bulk=True)

@bot.event
async def on_message_edit(before, after):
    if after.channel.id in config.no_log_channels:
        return
    if after.channel.type in [discord.ChannelType.public_thread, discord.ChannelType.private_thread]:
        if after.channel.parent.id in config.no_log_channels:
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
