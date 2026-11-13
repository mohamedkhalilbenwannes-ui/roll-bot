
import os, json, re, shlex, asyncio
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
GROUPS = {}  # message_id -> {title, place, time, roles: {emoji: {"name": str, "users": set}}, channel_id}

def parse_dungeon_args(text):
    # Use shlex to respect quotes
    try:
        tokens = shlex.split(text)
    except:
        tokens = text.split()
    title = "Dungeon Group"
    place = "-"
    time_val = "-"
    rest = tokens
    # If we have title+place+time + pairs: total-3 even and total>=5
    if len(tokens) >= 5 and (len(tokens)-3) % 2 == 0:
        # Heuristic: first 3 are title/place/time if first token is not an emoji and len>1
        # Check that tokens[3] is not emoji-like? Assume user used quoted form for this case.
        # We only treat as title/place/time if original text had quotes for first 3
        quoted = re.findall(r'"([^"]+)"', text)
        if len(quoted) >= 3:
            title, place, time_val = quoted[0], quoted[1], quoted[2]
            # rest tokens after the 3 quoted strings
            # Re-parse remainder: remove quoted parts
            remainder = text
            for q in quoted[:3]:
                remainder = remainder.replace(f'"{q}"', '', 1)
            rest = remainder.split()
        elif len(quoted) == 1:
            title = quoted[0]
            remainder = text.replace(f'"{quoted[0]}"', '', 1)
            rest = remainder.split()
    elif len(tokens) >= 1:
        quoted = re.findall(r'"([^"]+)"', text)
        if len(quoted) == 1:
            title = quoted[0]
            remainder = text.replace(f'"{quoted[0]}"', '', 1)
            rest = remainder.split()
        elif len(quoted) >= 2:
            # title + place, no time
            title, place = quoted[0], quoted[1]
            remainder = text
            for q in quoted[:2]:
                remainder = remainder.replace(f'"{q}"', '', 1)
            rest = remainder.split()
    # rest should be pairs role emoji
    roles = []
    i = 0
    while i+1 < len(rest)+1 and i+1 < len(rest):
        name = rest[i]
        emoji = rest[i+1]
        roles.append((name, emoji))
        i += 2
    return title, place, time_val, roles

def make_embed(g):
    e = discord.Embed(title=g["title"], color=0x2b2d31)
    e.add_field(name="📍 المكان", value=g["place"], inline=True)
    e.add_field(name="🕒 الوقت", value=g["time"], inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=False)
    filled = 0
    total = len(g["roles"])
    for emoji, info in g["roles"].items():
        users = info["users"]
        filled += len(users)
        if users:
            names = "\n".join([f"<@{uid}>" for uid in users])
        else:
            names = "OPEN"
        e.add_field(name=f"{emoji} {info['name']}", value=names, inline=True)
    e.set_footer(text=f"{filled}/{total} roles filled • React to join • One role per user")
    return e

async def refresh_group(msg_id):
    g = GROUPS.get(msg_id)
    if not g: return
    try:
        ch = bot.get_channel(g["channel_id"])
        if not ch: ch = await bot.fetch_channel(g["channel_id"])
        msg = await ch.fetch_message(msg_id)
        await msg.edit(embed=make_embed(g))
    except Exception as e:
        print("refresh err", e)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command(name="dungeon")
async def dungeon(ctx, *, args=""):
    if not args:
        await ctx.send('Usage: !dungeon "Title" "Place" "Time" Role1 🛡️ Role2 💚 ...\nExample: !dungeon "Static fame farm" "Caerleon" "21:00" Tank 🛡️ Healer 💚 SC 🔮 DPS1 ⚔️ DPS2 🏹')
        return
    title, place, time_val, roles = parse_dungeon_args(args)
    if not roles:
        await ctx.send("Each role needs one emoji. Example: !dungeon Tank 🛡️ Healer 💚")
        return
    g = {"title": title, "place": place, "time": time_val, "roles": {}, "channel_id": ctx.channel.id}
    for name, emoji in roles:
        g["roles"][emoji] = {"name": name, "users": set()}
    msg = await ctx.send(embed=make_embed(g))
    GROUPS[msg.id] = g
    for emoji in g["roles"].keys():
        try:
            await msg.add_reaction(emoji)
        except Exception as e:
            print("reaction err", e)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    g = GROUPS.get(payload.message_id)
    if not g: return
    emoji = str(payload.emoji)
    if emoji not in g["roles"]: return
    # One role per user: check if already in another role
    for em, info in g["roles"].items():
        if em != emoji and payload.user_id in info["users"]:
            # Remove new reaction
            try:
                ch = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
                msg = await ch.fetch_message(payload.message_id)
                user = payload.member or await bot.fetch_user(payload.user_id)
                await msg.remove_reaction(payload.emoji, user)
            except Exception as e:
                print(e)
            # DM warn
            try:
                user = payload.member or await bot.fetch_user(payload.user_id)
                await user.send(f"⚠️ You are already in **{g['roles'][em]['name']}** in **{g['title']}**. Remove that reaction first to join another role.")
            except: pass
            return
    # Add to this role
    g["roles"][emoji]["users"].add(payload.user_id)
    await refresh_group(payload.message_id)

@bot.event
async def on_raw_reaction_remove(payload):
    g = GROUPS.get(payload.message_id)
    if not g: return
    emoji = str(payload.emoji)
    if emoji in g["roles"]:
        g["roles"][emoji]["users"].discard(payload.user_id)
        await refresh_group(payload.message_id)

def get_target_group(ctx):
    if ctx.message.reference and ctx.message.reference.message_id:
        return GROUPS.get(ctx.message.reference.message_id), ctx.message.reference.message_id
    # fallback: last group in channel
    for mid, g in reversed(list(GROUPS.items())):
        if g["channel_id"] == ctx.channel.id:
            return g, mid
    return None, None

@bot.command(name="addrole")
async def addrole(ctx, role: str = None, emoji: str = None):
    g, mid = get_target_group(ctx)
    if not g or not role or not emoji:
        await ctx.send("Reply to the group and use: !addrole <role> <emoji>")
        return
    g["roles"][emoji] = {"name": role, "users": set()}
    await refresh_group(mid)
    try:
        ch = ctx.channel
        msg = await ch.fetch_message(mid)
        await msg.add_reaction(emoji)
    except: pass
    await ctx.send(f"Added {emoji} {role}")

@bot.command(name="removerole")
async def removerole(ctx, *, role: str = None):
    g, mid = get_target_group(ctx)
    if not g or not role:
        await ctx.send("Reply to the group and use: !removerole <role>")
        return
    for em in list(g["roles"].keys()):
        if g["roles"][em]["name"].lower() == role.lower():
            del g["roles"][em]
            await refresh_group(mid)
            await ctx.send(f"Removed {role}")
            return
    await ctx.send("Role not found")

@bot.command(name="rename")
async def rename(ctx, *, new_title: str = None):
    g, mid = get_target_group(ctx)
    if not g or not new_title:
        await ctx.send('Reply to the group and use: !rename "New Title"')
        return
    g["title"] = new_title.strip('"')
    await refresh_group(mid)
    await ctx.send(f"Title changed to {g['title']}")

@bot.command(name="setplace")
async def setplace(ctx, *, place: str = None):
    g, mid = get_target_group(ctx)
    if not g or not place:
        await ctx.send("Reply to the group and use: !setplace Caerleon")
        return
    g["place"] = place.strip('"')
    await refresh_group(mid)
    await ctx.send(f"Place set to {g['place']}")

@bot.command(name="settime")
async def settime(ctx, *, t: str = None):
    g, mid = get_target_group(ctx)
    if not g or not t:
        await ctx.send("Reply to the group and use: !settime 21:00")
        return
    g["time"] = t.strip('"')
    await refresh_group(mid)
    await ctx.send(f"Time set to {g['time']}")

@bot.command(name="clear")
async def clear(ctx):
    g, mid = get_target_group(ctx)
    if not g: return
    for info in g["roles"].values():
        info["users"].clear()
    await refresh_group(mid)
    await ctx.send("Group cleared")

@bot.command(name="help")
async def help_cmd(ctx):
    await ctx.send("**Dungeon Bot**\n!dungeon \"Title\" \"Place\" \"Time\" Tank 🛡️ Healer 💚 ...\nReply to group: !addrole, !removerole, !rename, !setplace, !settime, !clear\nOne role per user per group.")

bot.run(os.getenv("DISCORD_TOKEN"))
