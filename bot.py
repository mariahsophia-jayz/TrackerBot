import discord
import datetime
import os
from discord.ext import commands
from discord import app_commands

intents = discord.Intents.default()
intents.members = True
intents.invites = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

invite_tracker = {}
user_invites = {}

def similar_names(name1, name2):
    n1, n2 = name1.lower(), name2.lower()
    return n1[:4] == n2[:4] and n1 != n2

def get_alt_flags(inviter, new_member, invited_list):
    flags = []
    account_age = (datetime.datetime.utcnow() - new_member.created_at.replace(tzinfo=None)).days
    if account_age < 7:
        flags.append(f"Account only {account_age} day(s) old")
    if new_member.avatar is None:
        flags.append("No profile picture")
    if len(invited_list) >= 3:
        flags.append(f"Inviter has brought in {len(invited_list)} accounts total")
    if similar_names(inviter.name, new_member.name):
        flags.append("Similar username to inviter")
    return flags

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        try:
            invite_tracker[guild.id] = {inv.code: inv for inv in await guild.invites()}
        except:
            pass
    await tree.sync()
    print("Slash commands synced.")

@bot.event
async def on_invite_create(invite):
    invite_tracker[invite.guild.id][invite.code] = invite

@bot.event
async def on_member_join(member):
    guild = member.guild
    try:
        new_invites = {inv.code: inv for inv in await guild.invites()}
    except:
        return

    old_invites = invite_tracker.get(guild.id, {})
    used_inviter = None

    for code, inv in new_invites.items():
        old = old_invites.get(code)
        if old and inv.uses > old.uses:
            used_inviter = inv.inviter
            break

    invite_tracker[guild.id] = new_invites

    if not used_inviter:
        return

    if used_inviter.id not in user_invites:
        user_invites[used_inviter.id] = []

    account_age = (datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
    flags = get_alt_flags(used_inviter, member, user_invites[used_inviter.id])

    user_invites[used_inviter.id].append({
        "id": member.id,
        "name": str(member),
        "joined": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "account_age_days": account_age,
        "flags": flags
    })

    if len(flags) >= 2:
        log_channel = discord.utils.get(guild.text_channels, name="mod-logs")
        owner = guild.owner

        embed = discord.Embed(
            title="Alt Account Alert",
            description="A new member was flagged as a possible alt account.",
            color=discord.Color.red()
        )
        embed.add_field(name="New Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Invited By", value=f"{used_inviter} ({used_inviter.id})", inline=False)
        embed.add_field(name="Flags", value="\n".join(f"- {f}" for f in flags), inline=False)
        embed.add_field(name="Account Created", value=f"{account_age} day(s) ago", inline=False)
        embed.set_footer(text="Alt Tracker Bot")

        if log_channel:
            await log_channel.send(embed=embed)
        else:
            try:
                await owner.send(embed=embed)
            except:
                pass

@tree.command(name="altacc", description="Check how many alts a user may have invited")
@app_commands.describe(user="The user to check")
@app_commands.checks.has_permissions(manage_guild=True)
async def altacc(interaction: discord.Interaction, user: discord.Member):
    data = user_invites.get(user.id, [])

    if not data:
        await interaction.response.send_message(
            f"No invite data found for {user}. Either they have not invited anyone or the bot was offline when they did.",
            ephemeral=True
        )
        return

    flagged = [entry for entry in data if len(entry["flags"]) >= 2]
    total = len(data)
    flagged_count = len(flagged)

    embed = discord.Embed(
        title=f"Invite Report for {user}",
        color=discord.Color.orange()
    )
    embed.add_field(name="Total Invites Tracked", value=str(total), inline=True)
    embed.add_field(name="Flagged as Possible Alts", value=str(flagged_count), inline=True)

    if flagged:
        details = ""
        for entry in flagged:
            details += f"\n{entry['name']} (ID: {entry['id']})\n"
            details += f"  Joined: {entry['joined']}\n"
            details += f"  Account Age: {entry['account_age_days']} day(s)\n"
            details += f"  Flags: {', '.join(entry['flags'])}\n"
        embed.add_field(name="Flagged Accounts", value=details[:1024], inline=False)
    else:
        embed.add_field(name="Flagged Accounts", value="None detected so far.", inline=False)

    embed.set_footer(text="Alt Tracker Bot")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@altacc.error
async def altacc_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

bot.run(os.environ["DISCORD_TOKEN"])