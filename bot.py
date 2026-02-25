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
alert_settings = {}

def similar_names(name1, name2):
    n1, n2 = name1.lower(), name2.lower()
    return n1[:4] == n2[:4] and n1 != n2

def get_alt_flags(inviter, new_member, invited_list):
    flags = []
    account_age = (datetime.datetime.utcnow() - new_member.created_at.replace(tzinfo=None)).days
    if account_age < 30:
        flags.append(f"Account only {account_age} day(s) old")
    if new_member.avatar is None:
        flags.append("No profile picture")
    if len(invited_list) >= 2:
        flags.append(f"Inviter has brought in {len(invited_list)} accounts total")
    if similar_names(inviter.name, new_member.name):
        flags.append("Similar username to inviter")
    return flags

class AlertModal(discord.ui.Modal, title="Set Alert Channel"):
    description_input = discord.ui.TextInput(
        label="Alert Description",
        placeholder="Enter a custom message to include in alt alerts...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=200
    )

    def __init__(self, selected_channel_id):
        super().__init__()
        self.selected_channel_id = selected_channel_id

    async def on_submit(self, interaction: discord.Interaction):
        alert_settings[interaction.guild.id] = {
            "channel_id": self.selected_channel_id,
            "description": self.description_input.value or "A new member was flagged as a possible alt account."
        }
        channel = interaction.guild.get_channel(self.selected_channel_id)
        await interaction.response.send_message(
            f"Alert channel set to {channel.mention}.\nDescription: {self.description_input.value or 'Default message will be used.'}",
            ephemeral=True
        )

class ChannelSelect(discord.ui.View):
    def __init__(self, channels):
        super().__init__(timeout=60)
        self.selected_channel_id = None

        options = [
            discord.SelectOption(label=f"# {ch.name}", value=str(ch.id))
            for ch in channels[:25]
        ]

        select = discord.ui.Select(
            placeholder="Pick a channel for alt alerts...",
            options=options
        )
        select.callback = self.select_callback
        self.add_item(select)

        submit = discord.ui.Button(label="Submit", style=discord.ButtonStyle.green)
        submit.callback = self.submit_callback
        self.add_item(submit)

        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.red)
        close.callback = self.close_callback
        self.add_item(close)

    async def select_callback(self, interaction: discord.Interaction):
        self.selected_channel_id = int(interaction.data["values"][0])
        await interaction.response.defer()

    async def submit_callback(self, interaction: discord.Interaction):
        if not self.selected_channel_id:
            await interaction.response.send_message(
                "Please select a channel first.",
                ephemeral=True
            )
            return
        modal = AlertModal(self.selected_channel_id)
        await interaction.response.send_modal(modal)

    async def close_callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("Closed without saving.", ephemeral=True)
        self.stop()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_tracker[guild.id] = {inv.code: inv for inv in invites}
            print(f"Loaded {len(invites)} invites for guild {guild.name}")
        except Exception as e:
            print(f"Failed to load invites for {guild.name}: {e}")
    await tree.sync()
    print("Slash commands synced.")

@bot.event
async def on_invite_create(invite):
    invite_tracker[invite.guild.id][invite.code] = invite
    print(f"New invite created: {invite.code} by {invite.inviter}")

@bot.event
async def on_member_join(member):
    guild = member.guild
    print(f"Member joined: {member} in {guild.name}")
    try:
        new_invites = {inv.code: inv for inv in await guild.invites()}
    except Exception as e:
        print(f"Failed to get invites: {e}")
        return

    old_invites = invite_tracker.get(guild.id, {})
    used_inviter = None

    for code, inv in new_invites.items():
        old = old_invites.get(code)
        if old and inv.uses > old.uses:
            used_inviter = inv.inviter
            print(f"Invite used: {code} by inviter {used_inviter}")
            break

    invite_tracker[guild.id] = new_invites

    if not used_inviter:
        print(f"Could not find who invited {member} - no invite use change detected")
        return

    if used_inviter.id not in user_invites:
        user_invites[used_inviter.id] = []

    account_age = (datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
    flags = get_alt_flags(used_inviter, member, user_invites[used_inviter.id])
    print(f"Flags for {member}: {flags}")

    user_invites[used_inviter.id].append({
        "id": member.id,
        "name": str(member),
        "joined": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "account_age_days": account_age,
        "flags": flags
    })

    print(f"Saved invite data. {used_inviter} now has {len(user_invites[used_inviter.id])} tracked invites")

    if len(flags) >= 1:
        settings = alert_settings.get(guild.id)
        if settings:
            log_channel = guild.get_channel(settings["channel_id"])
            custom_desc = settings["description"]
        else:
            log_channel = discord.utils.get(guild.text_channels, name="mod-logs")
            custom_desc = "A new member was flagged as a possible alt account."

        owner = guild.owner

        embed = discord.Embed(
            title="Alt Account Alert",
            description=custom_desc,
            color=discord.Color.red()
        )
        embed.add_field(name="New Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Invited By", value=f"{used_inviter} ({used_inviter.id})", inline=False)
        embed.add_field(name="Flags", value="\n".join(f"- {f}" for f in flags), inline=False)
        embed.add_field(name="Account Created", value=f"{account_age} day(s) ago", inline=False)
        embed.set_footer(text="Alt Tracker Bot")

        if log_channel:
            await log_channel.send(embed=embed)
            print(f"Alert sent to {log_channel.name}")
        else:
            try:
                await owner.send(embed=embed)
                print("Alert sent to owner DM")
            except:
                print("Failed to send alert to owner DM")

async def get_all_accounts(guild, user):
    accounts = []
    member = guild.get_member(user.id)
    if member:
        accounts.append(member)
    invited = user_invites.get(user.id, [])
    for entry in invited:
        m = guild.get_member(entry["id"])
        if m:
            accounts.append(m)
    return accounts

@tree.command(name="altacc", description="Check how many alts a user may have invited")
@app_commands.describe(user="The user to check")
@app_commands.checks.has_permissions(manage_guild=True)
async def altacc(interaction: discord.Interaction, user: discord.Member):
    data = user_invites.get(user.id, [])
    print(f"altacc command used for {user}, data: {data}")

    if not data:
        await interaction.response.send_message(
            f"No invite data found for {user}. Either they have not invited anyone or the bot was offline when they did.",
            ephemeral=True
        )
        return

    flagged = [entry for entry in data if len(entry["flags"]) >= 1]
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

@tree.command(name="setalert", description="Set which channel to send alt account alerts to")
@app_commands.checks.has_permissions(manage_guild=True)
async def setalert(interaction: discord.Interaction):
    text_channels = [ch for ch in interaction.guild.text_channels]
    if not text_channels:
        await interaction.response.send_message("No text channels found.", ephemeral=True)
        return

    view = ChannelSelect(text_channels)
    await interaction.response.send_message(
        "Select a channel for alt alerts then tap Submit. Tap Close to cancel.",
        view=view,
        ephemeral=True
    )

@tree.command(name="banall", description="Ban a user and all their invited alt accounts")
@app_commands.describe(user="The user to ban along with their alts", reason="Reason for the ban")
@app_commands.checks.has_permissions(ban_members=True)
async def banall(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    await interaction.response.defer(ephemeral=True)
    accounts = await get_all_accounts(interaction.guild, user)
    banned = []
    failed = []

    for member in accounts:
        try:
            await member.ban(reason=f"{reason} - Alt ban by {interaction.user}")
            banned.append(str(member))
        except:
            failed.append(str(member))

    embed = discord.Embed(title="Ban All Report", color=discord.Color.red())
    embed.add_field(name="Banned", value="\n".join(banned) if banned else "None", inline=False)
    embed.add_field(name="Failed", value="\n".join(failed) if failed else "None", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="Alt Tracker Bot")
    await interaction.followup.send(embed=embed, ephemeral=True)

@tree.command(name="kickall", description="Kick a user and all their invited alt accounts")
@app_commands.describe(user="The user to kick along with their alts", reason="Reason for the kick")
@app_commands.checks.has_permissions(kick_members=True)
async def kickall(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    await interaction.response.defer(ephemeral=True)
    accounts = await get_all_accounts(interaction.guild, user)
    kicked = []
    failed = []

    for member in accounts:
        try:
            await member.kick(reason=f"{reason} - Alt kick by {interaction.user}")
            kicked.append(str(member))
        except:
            failed.append(str(member))

    embed = discord.Embed(title="Kick All Report", color=discord.Color.orange())
    embed.add_field(name="Kicked", value="\n".join(kicked) if kicked else "None", inline=False)
    embed.add_field(name="Failed", value="\n".join(failed) if failed else "None", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="Alt Tracker Bot")
    await interaction.followup.send(embed=embed, ephemeral=True)

@tree.command(name="timeoutall", description="Timeout a user and all their invited alt accounts")
@app_commands.describe(
    user="The user to timeout along with their alts",
    minutes="How many minutes to timeout for",
    reason="Reason for the timeout"
)
@app_commands.checks.has_permissions(moderate_members=True)
async def timeoutall(interaction: discord.Interaction, user: discord.Member, minutes: int = 60, reason: str = "No reason provided"):
    await interaction.response.defer(ephemeral=True)
    accounts = await get_all_accounts(interaction.guild, user)
    timed_out = []
    failed = []

    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)

    for member in accounts:
        try:
            await member.timeout(until, reason=f"{reason} - Alt timeout by {interaction.user}")
            timed_out.append(str(member))
        except:
            failed.append(str(member))

    embed = discord.Embed(title="Timeout All Report", color=discord.Color.yellow())
    embed.add_field(name="Timed Out", value="\n".join(timed_out) if timed_out else "None", inline=False)
    embed.add_field(name="Failed", value="\n".join(failed) if failed else "None", inline=False)
    embed.add_field(name="Duration", value=f"{minutes} minute(s)", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="Alt Tracker Bot")
    await interaction.followup.send(embed=embed, ephemeral=True)

@banall.error
async def banall_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You do not have permission to ban members.", ephemeral=True)

@kickall.error
async def kickall_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You do not have permission to kick members.", ephemeral=True)

@timeoutall.error
async def timeoutall_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You do not have permission to timeout members.", ephemeral=True)

@altacc.error
async def altacc_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

@setalert.error
async def setalert_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

bot.run(os.environ["DISCORD_TOKEN"])
