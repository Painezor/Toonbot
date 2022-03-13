"""Moderation Commands"""
import datetime
from typing import Optional, Literal

from discord import Interaction, Member, app_commands, Colour, Embed, TextChannel, HTTPException, Forbidden, Object
from discord.ext import commands

from ext.utils import embed_utils, view_utils, timed_events


# TODO: User Commands Pass
# TODO: Modals pass -> Say command, pin command, topic command.
# TODO: Grouped Commands pass
# TODO: Slash attachments pass
# TODO: Permissions Pass.
# TODO: Banlist dropdown -> Unban.


class Mod(commands.Cog):
    """Guild Moderation Commands"""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command()
    @app_commands.describe(message="text to send", destination="target channel")
    async def say(self, interaction: Interaction, message: str, destination: Optional[TextChannel] = None):
        """Say something as the bot in specified channel"""
        if not interaction.guild:
            return await self.bot.error(interaction, "This command cannot be used in DMs")

        if destination is None:
            destination = interaction.channel

        if destination.guild.id != interaction.guild.id:
            return await self.bot.error(interaction, "You cannot send messages to other servers.")

        if not interaction.permissions.manage_messages:
            if not interaction.user.id == self.bot.owner_id:
                return await self.bot.error(interaction, "You need manage_messages permissions to do that")

        if len(message) > 2000:
            return await self.bot.error(interaction, "Message too long. Keep it under 2000.")

        try:
            await destination.send(message)
            await self.bot.reply(interaction, content="Message sent.")
        except Forbidden:
            return await self.bot.error(interaction, "I can't send messages to that channel.")

    @app_commands.command()
    @app_commands.describe(new_topic="Type the new topic for this channel..")
    async def topic(self, interaction: Interaction, new_topic: str):
        """Set the topic for the current channel"""
        if not interaction.guild:
            return await self.bot.error(interaction, "This command cannot be used in DMs")

        if not interaction.permissions.manage_channels:
            err = "You need manage_channels permissions to edit the channel topic."
            return await self.bot.error(interaction, err)

        await interaction.channel.edit(topic=new_topic)
        await self.bot.reply(interaction, content=f"{interaction.channel.mention} Topic updated")

    @app_commands.command()
    @app_commands.describe(message="Type a message to be pinned in this channel.")
    async def pin(self, interaction: Interaction, message: str):
        """Pin a message to the current channel"""
        if not interaction.permissions.manage_channels:
            return await self.bot.error(interaction, "You need manage_channels permissions to pin a message.")

        message = await self.bot.reply(interaction, content=message)
        await message.pin()

    @app_commands.command()
    @app_commands.describe(member="Pick a user to rename", new_nickname="Choose a new nickname for the member")
    async def rename(self, interaction: Interaction, member: Member, new_nickname: str):
        """Rename a member"""
        if not interaction.guild:
            return await self.bot.error(interaction, "This command cannot be used in DMs")

        if not interaction.permissions.manage_nicknames:
            msg = "You need manage_nicknames permissions to rename a user"
            return await self.bot.error(interaction, msg)

        try:
            await member.edit(nick=new_nickname)
        except Forbidden:
            await self.bot.error(interaction, "I can't change that member's nickname.")
        except HTTPException:
            await self.bot.error(interaction, "❔ Member edit failed.")
        else:
            await self.bot.reply(interaction, content=f"{member.mention} has been renamed.")

    @app_commands.command()
    @app_commands.describe(member="Pick a user to kick", reason="provide a reason for kicking the user")
    async def kick(self, interaction: Interaction, member: Member, reason: str = "unspecified reason."):
        """Kicks the user from the server"""
        if not interaction.guild:
            return await self.bot.error(interaction, "This command cannot be used in DMs")

        if not interaction.permissions.kick_members:
            msg = "You need kick_members permissions to rename a user"
            return await self.bot.error(interaction, msg)

        try:
            await member.kick(reason=f"{interaction.user}: {reason}")
        except Forbidden:
            await self.bot.error(interaction, f"I can't kick {member.mention}")
        else:
            await self.bot.reply(interaction, content=f"{member.mention} was kicked.")

    @app_commands.command()
    @app_commands.describe(member="Pick a user to ban",
                           user_ids="enter a comma separated list of user ids to ban",
                           reason="provide a reason for kicking the user",
                           delete_days="delete messages from the last x days")
    async def ban(self, interaction: Interaction,
                  delete_days: Literal[0, 1, 2, 3, 4, 5, 6, 7],
                  member: Optional[Member] = None,
                  user_ids: Optional[str] = None,
                  reason: str = "Not specified"):
        """Bans a member (or list of User IDs) from the server, deletes all messages for the last x days"""
        if not interaction.guild:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")
        if not interaction.permissions.ban_members:
            return await self.bot.error(interaction, "You need ban_members permissions to ban someone.")

        e = Embed(title="Users Banned", description="")
        if reason is not None:
            e.add_field(name="reason", value=reason)
        if delete_days != Literal[0]:
            e.add_field(name="Deleted Messages", value=f"Messages from the last {delete_days} were deleted.")

        if member is not None:
            e.description = f"☠ {member.mention}"
            try:
                await member.ban(reason=f"{interaction.user.name}: {reason}", delete_message_days=delete_days)
                await self.bot.reply(interaction, embed=e)
            except Forbidden:
                return await self.bot.error(interaction, f"I can't ban {member.mention}.")

        if user_ids is not None:
            targets = [int(i.strip()) for i in ','.split(user_ids)]

            for i in targets:
                target = await self.bot.fetch_user(int(i))
                e.description += f'☠ UserID {i} {target}'
                try:
                    await self.bot.http.ban(i, interaction.guild.id)
                except HTTPException:
                    e.description += f"⚠ Banning failed for {i}."
            await self.bot.reply(interaction, embed=e)

    @app_commands.command()
    @app_commands.describe(user_id="Enter the user ID# of the person to unban")
    async def unban(self, interaction: Interaction, user_id: str):
        """Unbans a user from the server"""
        if not interaction.guild:
            return await self.bot.error(interaction, "This command cannot be ran in DMs")

        if not interaction.permissions.ban_members:
            return await self.bot.error(interaction, "You need ban_members permissions to unban someone.")

        try:
            user_id = int(user_id)
        except ValueError:
            return await self.bot.error(interaction, "Invalid user ID provided.")

        user = Object(user_id)

        try:
            await interaction.guild.unban(user)
        except HTTPException:
            await self.bot.error(interaction, "I can't unban that user.")
        else:
            target = await self.bot.fetch_user(user_id)
            await self.bot.reply(interaction, content=f"{user} | {target} was unbanned")
            e = Embed(title="Unbanned", description=f"You have been unbanned from {interaction.guild.name}")
            await target.send(embed=e)

    # TODO: Banlist as View
    @app_commands.command()
    async def banlist(self, interaction):
        """Show the ban list for the server"""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be used in DMs.")

        if not interaction.permissions.view_audit_log:
            return await self.bot.error(interaction, "You need view_audit_log permissions to view the ban list.")

        ban_lines = [f"{x.id} | {x.user.name}#{x.user.discriminator}"
                     f"```yaml\n{x.reason}```" for x in await interaction.guild.bans()]

        if not ban_lines:
            ban_lines = ["No bans found"]

        e = Embed(color=0x111)
        n = f"{interaction.guild.name} ban list"
        _ = interaction.guild.icon.url if interaction.guild.icon is not None else None
        e.set_author(name=n, icon_url=_)

        embeds = embed_utils.rows_to_embeds(e, ban_lines)
        view = view_utils.Paginator(interaction, embeds)
        await view.update()

    @app_commands.command()
    @app_commands.describe(number="Number of messages to delete.")
    async def clean(self, interaction: Interaction, number: int = None):
        """Deletes my messages from the last x messages in channel"""
        if not interaction.permissions.manage_messages:
            err = 'You need manage_messages permissions to clear messages.'
            return await self.bot.error(interaction, err)

        def is_me(m):
            """Return only messages sent by the bot."""
            return m.author.id == self.bot.user.id

        number = 10 if number is None else number

        deleted = await interaction.channel.purge(limit=number, check=is_me)
        c = f'♻ Deleted {len(deleted)} bot message{"s" if len(deleted) > 1 else ""}'
        await self.bot.reply(interaction, content=c, ephemeral=True)

    @app_commands.command()
    @app_commands.describe(minutes="number of minutes to timeout for", hours="number of hours to timeout for",
                           days="number of days to timeout for", reason="provide a reason for the timeout")
    async def timeout(self, interaction: Interaction,
                      member: Member,
                      minutes: app_commands.Range[int, 0, 60] = 0,
                      hours: app_commands.Range[int, 0, 24] = 0,
                      days: app_commands.Range[int, 0, 7] = 0,
                      reason: str = "Not specified"):
        """Timeout a user for the specified amount of time."""
        if minutes == 0 and hours == 0 and days == 0:
            return await self.bot.error(interaction, "You need to specify a duration")

        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be used in DMs")

        if not interaction.permissions.moderate_members:
            return await self.bot.error(interaction, "You need moderate_members permissions to time someone out.")

        delta = datetime.timedelta(minutes=minutes, hours=hours, days=days)

        try:
            await member.timeout(delta, reason=reason)
            e = Embed(title="User Timed Out", colour=Colour.dark_magenta())
            t = timed_events.Timestamp(datetime.datetime.now(datetime.timezone.utc) + delta).long
            e.description = f"{member.mention} was timed out.\nTimeout ends: {t}"
            await self.bot.reply(interaction, embed=e)
        except HTTPException:
            await self.bot.error(interaction, "I can't time out that user.")

    @app_commands.command()
    @app_commands.describe(member="The user to untimeout", reason="reason for ending the timeout")
    async def untimeout(self, interaction: Interaction, member: Member, reason: str = None):
        """End the timeout for a user."""
        if interaction.guild is None:
            return await self.bot.error(interaction, "This command cannot be used in DMs")

        if not interaction.permissions.moderate_members:
            return await self.bot.error(interaction, "You need moderate_members permissions to cancel a timeout.")

        reason = f"{interaction.user}" if reason is None else f"{interaction.user}: reason"

        try:
            await member.remove_timeout(reason=reason)
            e = Embed(title="User Timed Out", color=Colour.dark_magenta())
            e.description = f"{member.mention} is no longer timed out."
            await self.bot.reply(interaction, embed=e)
        except HTTPException:
            await self.bot.error(interaction, "I can't un-timeout that user.")

    # Listeners
    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Create database entry for new guild"""
        await self.create_guild(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Delete guild's info upon leaving one."""
        await self.delete_guild(guild.id)

    async def create_guild(self, guild_id):
        """Insert the database entry for a new guild"""
        q = """INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, guild_id)
        finally:
            await self.bot.db.release(connection)
            
    async def delete_guild(self, guild_id):
        """Remove a guild's settings from the database"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute("""DELETE FROM guild_settings WHERE guild_id = $1""", guild_id)
        finally:
            await self.bot.db.release(connection)


def setup(bot):
    """Load the mod cog into the bot"""
    bot.add_cog(Mod(bot))
