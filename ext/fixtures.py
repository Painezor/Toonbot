"""Lookups of Live Football Data for teams, fixtures, and competitions."""
import datetime
import typing
from collections import defaultdict
from copy import deepcopy
from importlib import reload

import discord
from discord.ext import commands

# D.py
from ext.utils import browser, timed_events
# Custom Utils
from ext.utils import transfer_tools, football, embed_utils


class Fixtures(commands.Cog):
    """Lookups for past, present and future football matches."""

    def __init__(self, bot):
        self.bot = bot

        if not hasattr(bot, "browser"):
            self.bot.loop.create_task(browser.make_browser(bot))

        for package in [transfer_tools, football, embed_utils, browser, timed_events]:
            reload(package)
    
    # Master picker.
    async def _search(self, ctx, qry, mode=None) -> typing.Union[football.Team, football.Competition, None]:
        # Handle stupidity
        if qry is None:
            if ctx.guild is not None:
                default = await self._fetch_default(ctx, mode)
                if default is not None:
                    page = await self.bot.browser.newPage()
                    if mode == "team":
                        team_id = default.split('/')[-1]
                        fsr = await football.Team.by_id(team_id, page)
                    else:
                        fsr = await football.Competition.by_link(default, page)
                    await page.close()
                    return fsr
            return None
        
        search_results = await football.get_fs_results(qry)
        
        if not search_results:
            output = f'No search results found for query: `{qry}`'
            if mode is not None:
                output += f" ({mode})"
            await self.bot.reply(ctx, text=output)
            return None
        
        pt = 0 if mode == "league" else 1 if mode == "team" else None  # Mode is a hard override.
        if pt is not None:
            item_list = [i.title for i in search_results if i.participant_type_id == pt]  # Check for specifics.
        else:  # All if no mode
            item_list = [i.title for i in search_results]
        
        if not item_list:
            await self.bot.reply(ctx, text=f"No matching {mode} found for query {qry}")
            return None
        
        e = discord.Embed()
        e.colour = discord.Colour.dark_green()
        e.title = "Flashscore Search: Multiple results found"
        e.set_thumbnail(url=ctx.me.avatar_url)

        index = await embed_utils.page_selector(ctx, item_list, e, preserve_footer=False)

        if index == "cancelled":
            await self.bot.reply(ctx, text="Lookup cancelled.")
            return None
        elif index is None:
            await self.bot.reply(ctx, text="Timed out waiting for your response.")
            return None
        elif index == -1:
            await self.bot.reply(ctx, f"No matching results for query: {qry}")
            return None

        item = search_results[index]

        assert isinstance(item, (football.Team, football.Competition)), "FlashScoreResult was not a Team or League!"
        return item
    
    # Fetch from bot games.
    async def _pick_game(self, ctx, q: str, search_type=None) -> typing.Union[football.Fixture, None] or False:
        q = q.lower()
        
        if search_type == "team":
            matches = [i for i in self.bot.games if q in f"{i.home.lower()} vs {i.away.lower()}"]
        else:
            matches = [i for i in self.bot.games if q in (i.home + i.away + i.league + i.country).lower()]
        if not matches:
            return None

        base_embed = discord.Embed()
        base_embed.set_footer(text="If you did not want a live game, click the '🚫' reaction to search all teams")
        base_embed.title = "Select from live games"
        base_embed.colour = discord.Colour.blurple()

        pickers = [i.scores_row for i in matches]
        index = await embed_utils.page_selector(ctx, pickers, base_embed=base_embed, confirm_single=True,
                                                preserve_footer=False)

        if index is None or index == -1 or index == "cancelled":
            return None  # timeout or abort.

        return matches[index]
    
    async def _fetch_default(self, ctx, mode=None):
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            r = await connection.fetchrow("""SELecT * FROM scores_settings WHERE (guild_id) = $1
                 AND (default_league is NOT NULL OR default_team IS NOT NULL)""", ctx.guild.id)
        await self.bot.db.release(connection)
        if r:
            team = r["default_team"]
            league = r["default_league"]
            # Decide if found, yell if not.
            if team or league:
                if mode == "team":
                    return team if team else league
                return league if league else team
        return None
    
    @commands.command(aliases=['fx'], usage="<Team or league name to search for>")
    async def fixtures(self, ctx, *, qry: commands.clean_content = None):
        """Fetch upcoming fixtures for a team or league.
        Navigate pages using reactions."""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._search(ctx, qry)

        if fsr is None:
            return

        page = await self.bot.browser.newPage()
        fx = await fsr.get_fixtures(page, '/fixtures')
        await page.close()

        fixtures = [str(i) for i in fx]

        fixtures = ["No Fixtures Found :("] if not fixtures else fixtures

        embed = await fsr.base_embed
        embed.title = f"≡ Fixtures for {embed.title}" if embed.title else "≡ Fixtures "

        embeds = embed_utils.rows_to_embeds(embed, fixtures)

        await embed_utils.paginate(ctx, embeds)
    
    @commands.command(aliases=['rx'], usage="<Team or league name to search for>")
    async def results(self, ctx, *, qry: commands.clean_content = None):
        """Get past results for a team or league.
        Navigate pages using reactions."""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._search(ctx, qry)

        if fsr is None:
            return

        page = await self.bot.browser.newPage()
        results = await fsr.get_fixtures(page, '/results')
        await page.close()

        results = [str(i) for i in results]
        results = ["No Fixtures Found :("] if not results else results

        embed = await fsr.base_embed
        embed.title = f"≡ Results for {embed.title}" if embed.title else "≡ Results "
        embeds = embed_utils.rows_to_embeds(embed, results)

        await embed_utils.paginate(ctx, embeds)
    
    @commands.command(usage="[league or team to search for or leave blank to use server's default setting]")
    async def table(self, ctx, qry: commands.clean_content = None):
        """Get table for a league"""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._pick_game(ctx, str(qry)) if qry is not None else None

        if fsr is None:
            fsr = await self._search(ctx, qry)

        if fsr is None:
            return

        if isinstance(fsr, football.Team):  # Select from team's leagues.

            page = await self.bot.browser.newPage()
            all_fixtures = await fsr.get_fixtures(page)
            await page.close()

            unique_comps = []
            for i in all_fixtures:
                if i.full_league not in [x.full_league for x in unique_comps]:
                    unique_comps.append(i)

            for_picking = [i.full_league for i in unique_comps]
            embed = await fsr.base_embed
            index = await embed_utils.page_selector(ctx, for_picking, deepcopy(embed), preserve_footer=False)
            if index is None or index == "cancelled":
                return  # rip
            if index == -1:
                return await self.bot.reply(f'🚫 No competitions found for {fsr.title}.')

            fsr = unique_comps[index]

        page = await self.bot.browser.newPage()
        image = await fsr.get_table(page)
        await page.close()

        embed = await fsr.base_embed
        if image is None:
            embed.description = "No table found."
            return await self.bot.reply(ctx, embed=embed)

        time = timed_events.timestamp(mode="long")

        embed.description = f"Table as of {time}"
        fn = f"Table-{qry}.png".strip()
        await embed_utils.embed_image(ctx, embed, image, filename=fn)
    
    @commands.command(usage="[team to search for stats of game of]")
    async def stats(self, ctx, *, qry: commands.clean_content):
        """Look up the stats for a game."""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._pick_game(ctx, str(qry), search_type="team")
        
        if fsr is None:
            fsr = await self._search(ctx, qry)
        
        if fsr is None:
            return  # rip
        
        other_embed = await fsr.base_embed
        
        page = await self.bot.browser.newPage()
        try:
            all_fixtures = await fsr.get_fixtures(page)
            embed = await fsr.base_embed
            index = await embed_utils.page_selector(ctx, all_fixtures, embed, preserve_footer=False)
            if index is None or index == "cancelled" or index == -1:
                return  # rip
            fsr = all_fixtures[index]
        except AttributeError:
            pass
        finally:
            await page.close()
        
        page = await self.bot.browser.newPage()
        image = await fsr.get_stats(page)
        await page.close()
        
        embed = await fsr.base_embed
        embed.colour = other_embed.colour
        embed.set_thumbnail(url=other_embed.thumbnail.url)
        
        if image is None:
            embed.description = "No stats found."
            return await self.bot.reply(ctx, embed=embed)
        
        await embed_utils.embed_image(ctx, embed, image)
    
    @commands.command(usage="<team to search for>", aliases=["formations", "lineup", "lineups"])
    async def formation(self, ctx, *, qry: commands.clean_content):
        """Get the formations for the teams in one of today's games"""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._pick_game(ctx, str(qry), search_type="team")
        
        if fsr is None:
            fsr = await self._search(ctx, qry)
        
        if fsr is None:
            return  # rip
        
        other_embed = await fsr.base_embed
        
        page = await self.bot.browser.newPage()
        try:
            all_fixtures = await fsr.get_fixtures(page)
            embed = await fsr.base_embed
            index = await embed_utils.page_selector(ctx, all_fixtures, embed, preserve_footer=False)
            if index is None or index == "cancelled" or index == -1:
                return  # rip
            fsr = all_fixtures[index]
        except AttributeError:
            pass
        finally:
            await page.close()
        
        page = await self.bot.browser.newPage()
        image = await fsr.get_formation(page)
        await page.close()
        
        embed = await fsr.base_embed
        embed.colour = other_embed.colour
        embed.set_thumbnail(url=other_embed.thumbnail.url)
        
        if image is None:
            embed.description = "No formation data found."
            return await self.bot.reply(ctx, embed=embed)
    
        await embed_utils.embed_image(ctx, embed, image)
    
    @commands.command()
    async def summary(self, ctx, *, qry: commands.clean_content):
        """Get a summary for one of today's games."""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._pick_game(ctx, str(qry), search_type="team")
        
        if fsr is None:
            fsr = await self._search(ctx, qry)
        
        if fsr is None:
            return  # rip
        
        other_embed = await fsr.base_embed
        
        page = await self.bot.browser.newPage()
        try:
            all_fixtures = await fsr.get_fixtures(page)
            embed = await fsr.base_embed
            index = await embed_utils.page_selector(ctx, all_fixtures, embed, preserve_footer=False)
            if index is None or index == "cancelled" or index == -1:
                await page.close()
                return  # rip
            fsr = all_fixtures[index]
        except AttributeError:
            pass

        image = await fsr.get_summary(page)
        await page.close()
        
        embed = await fsr.base_embed
        embed.colour = other_embed.colour
        embed.set_thumbnail(url=other_embed.thumbnail.url)
        
        if image is None:
            embed.description = "No summary found."
            return await self.bot.reply(ctx, embed=embed)
        
        await embed_utils.embed_image(ctx, embed, image)
    
    @commands.command(aliases=["form"], usage="<Team name to search for>")
    async def h2h(self, ctx, *, qry: commands.clean_content):
        """Get Head to Head data for a team fixtures"""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._pick_game(ctx, str(qry), search_type="team") if qry is not None else None
        if fsr is False:
            return
        
        if fsr is None:
            fsr = await self._search(ctx, qry, mode="team")
        
        if fsr is None:
            return

        if isinstance(fsr, football.Team):  # Select from team's leagues.
            page = await self.bot.browser.newPage()
            choices = await fsr.get_fixtures(page)
            await page.close()
            
            e = await fsr.base_embed
            e.title = f"Games for {fsr.title}"
            
            index = await embed_utils.page_selector(ctx, choices, deepcopy(e), preserve_footer=False)
            if index is None:
                return  # rip or cancelled
            fsr = choices[index]
        
        page = await self.bot.browser.newPage()
        try:
            h2h = await fsr.head_to_head(page)
        except IndexError as e:
            print(e)
            return await self.bot.reply(ctx, 'No Head to head data found.')
        finally:
            await page.close()
        
        e = await fsr.base_embed
        
        e.title = f"Head to Head data for {fsr.home} vs {fsr.away}"
        
        for k, v in h2h.items():
            e.add_field(name=k, value="\n".join([str(i) for i in v]), inline=False)
    
        await self.bot.reply(ctx, embed=e)
    
    # Team specific.
    @commands.command(aliases=["suspensions"], usage="<Team name to search for>")
    async def injuries(self, ctx, *, qry: commands.clean_content = None):
        """Get a team's current injuries"""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._search(ctx, qry, mode="team")

        if fsr is None:
            return

        assert isinstance(fsr, football.Team), f"Expected football.Team, got {type(fsr)}"

        page = await self.bot.browser.newPage()
        players = await fsr.get_players(page)
        await page.close()

        embed = await fsr.base_embed
        players = [f"{i.flag} [{i.name}]({i.url}) ({i.position}): {i.injury}" for i in players if i.injury and i]
        players = players if players else ['No injuries found']
        embed.title = f"≡ Injuries for {embed.title}" if embed.title else "≡ Injuries "
        embeds = embed_utils.rows_to_embeds(embed, players)
        await embed_utils.paginate(ctx, embeds)
    
    @commands.command(aliases=["team", "roster"], usage="<Team name to search for>")
    async def squad(self, ctx, *, qry: commands.clean_content = None):
        """Lookup a team's squad members"""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._search(ctx, qry, mode="team")

        if fsr is None:
            return

        page = await self.bot.browser.newPage()

        assert isinstance(fsr, football.Team), f"Expected type: football.Team, got type {type(fsr)}"

        players = await fsr.get_players(page)
        await page.close()
        srt = sorted(players, key=lambda x: x.number)
        embed = await fsr.base_embed
        embed.title = f"≡ Squad for {embed.title}" if embed.title else "≡ Squad "
        players = [f"`{str(i.number).rjust(2)}`: {i.flag} [{i.name}]({i.url}) {i.position}{i.injury}" for i in
                   srt if i]
        embeds = embed_utils.rows_to_embeds(embed, players)
        
        await embed_utils.paginate(ctx, embeds)
    
    @commands.command(invoke_without_command=True, aliases=['sc'], usage="<team or league to search for>")
    async def scorers(self, ctx, *, qry: commands.clean_content = None):
        """Get top scorers from a league, or search for a team and get their top scorers in a league."""
        await self.bot.reply(ctx, text="Searching...", delete_after=5)
        fsr = await self._search(ctx, qry)
        if fsr is None:
            return
            
        if isinstance(fsr, football.Competition):
            page = await self.bot.browser.newPage()
            try:
                sc = await fsr.get_scorers(page)
            except ValueError:
                print(f'Debug Log: Scorers Not Found for League {fsr.url}')
                return await self.bot.reply(ctx, 'Scorers unavailable for this league.')
            except Exception as e:
                raise e
            finally:
                await page.close()

            embed = await fsr.base_embed
            players = [i.scorer_row for i in sc]
            embed.title = f"≡ Top Scorers for {embed.title}" if embed.title else "≡ Top Scorers "
        elif isinstance(fsr, football.Team):
            page = await self.bot.browser.newPage()
            choices = await fsr.get_competitions(page)
            await page.close()

            embed = await fsr.base_embed
            embed.set_author(name="Pick a competition")
            index = await embed_utils.page_selector(ctx, choices, deepcopy(embed))
            if index is None or index == "cancelled" or index == -1:
                return  # rip

            page = await self.bot.browser.newPage()
            players = await fsr.get_players(page, index)
            await page.close()

            players = sorted([i for i in players if i.goals > 0], key=lambda x: x.goals, reverse=True)
            players = [f"{i.flag} [{i.name}]({i.url}) {i.goals} in {i.apps} appearances" for i in players]

            embed = await fsr.base_embed

            embed.title = f"≡ Top Scorers for {embed.title} in {choices[index]}" if embed.title \
                else f"Top Scorers in {choices[index]}"
        else:
            raise ValueError(f'Expected football.Team or football.Competition, but got {type(fsr)}!')
        
        embeds = embed_utils.rows_to_embeds(embed, players)
        
        await embed_utils.paginate(ctx, embeds)
    
    @commands.command(usage="<league to search for>")
    async def scores(self, ctx, *, search_query: commands.clean_content = ""):
        """Fetch current scores for a specified league"""
        embeds = []
        e = discord.Embed()
        e.colour = discord.Colour.blurple()
        if search_query:
            e.set_author(name=f'Live Scores matching search "{search_query}"')
        else:
            e.set_author(name="Live Scores for all known competitions")

        e.timestamp = datetime.datetime.now()
        dtn = timed_events.timestamp(mode="long")
        q = str(search_query).lower()

        time = f"\nScores as of: {dtn}"

        matches = [i for i in self.bot.games if q in (i.home + i.away + i.league + i.country).lower()]

        if not matches:
            e.description = "No results found!"
            return await embed_utils.paginate(ctx, [e])

        game_dict = defaultdict(list)
        for i in matches:
            game_dict[i.full_league].append(i.scores_row)

        for league, games in sorted(game_dict.items()):
            league_embeds = embed_utils.rows_to_embeds(e, games, header=f"**{league}**", footer=time)
            embeds += league_embeds
        await embed_utils.paginate(ctx, embeds)
    
    @commands.command(usage="<Team or Stadium name to search for.>")
    async def stadium(self, ctx, *, query: commands.clean_content):
        """Lookup information about a team's stadiums"""
        stadiums = await football.get_stadiums(query)
        
        item_list = [str(i) for i in stadiums]
        
        index = await embed_utils.page_selector(ctx, item_list)
        
        if index is None or index == -1:
            return  # Timeout or abort.
        
        await self.bot.reply(ctx, embed=await stadiums[index].to_embed)

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def default(self, ctx):
        """Check the defai;t team and league for your server's Fixture commands"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            record = await connection.fetchrow("""SELecT * FROM scores_settings
            WHERE (guild_id) = $1 AND (default_league is NOT NULL OR default_team IS NOT NULL)""", ctx.guild.id)
        await self.bot.db.release(connection)
        if not record:
            return await self.bot.reply(ctx, text=f"{ctx.guild.name} does not currently have any defaults set.")
        
        league = "not set." if record["default_league"] is None else record["default_league"]
        team = "not set." if record["default_team"] is None else record["default_team"]
        return await self.bot.reply(ctx, text=f"Your default league is: <{league}>"
                                              f"\nYour default team is: <{team}>")
    
    @default.group()
    @commands.has_permissions(manage_guild=True)
    async def team(self, ctx, qry: commands.clean_content = None):
        """Set a default team for your server's Fixture commands"""
        await self.bot.reply(ctx, text=f'Searching for {qry}...', delete_after=5)
        fsr = await self._search(ctx, qry, mode="team")

        if fsr is None:
            return

        assert isinstance(fsr, football.Team), f"Expected football.Team, got {type(fsr)}"

        url = fsr.url
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(f"""INSERT INTO scores_settings (guild_id, default_team) VALUES ($1,$2)
                 ON CONFLICT (guild_id) DO UPDATE SET default_team = $2 WHERE excluded.guild_id = $1
           """, ctx.guild.id, url)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f'Your Fixtures commands will now use {fsr.name} as a default team')
    
    @team.command(name="reset", aliases=["none"])
    @commands.has_permissions(manage_guild=True)
    async def reset_team(self, ctx):
        """Unsets your server's default team for your Fixtures commands"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(f"""INSERT INTO scores_settings (guild_id, default_team)  VALUES ($1,$2)
                ON CONFLICT (guild_id) DO UPDATE SET default_team = $2 WHERE excluded.guild_id = $1""",
                                     ctx.guild.id, None)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text='Your Fixtures commands will no longer use a default team.')
    
    @default.group(invoke_without_commands=True)
    @commands.has_permissions(manage_guild=True)
    async def league(self, ctx, qry: commands.clean_content = None):
        """Set a default league for your server's Fixture commands"""
        await self.bot.reply(ctx, text=f'Searching for {qry}...', delete_after=5)
        fsr = await self._search(ctx, qry, mode="league")

        if fsr is None:
            return

        assert isinstance(fsr, football.Competition), "Expected football."

        url = fsr.url
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(f"""INSERT INTO scores_settings (guild_id, default_league) VALUES ($1,$2)
                   ON CONFLICT (guild_id) DO UPDATE SET default_league = $2 WHERE excluded.guild_id = $1
             """, ctx.guild.id, url)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text=f'Your Fixtures commands will now use {fsr.title} as a default league')
    
    @league.command(name="reset", aliases=["none"])
    @commands.has_permissions(manage_guild=True)
    async def reset_league(self, ctx):
        """Unsets your server's default league for your Fixtures commands"""
        connection = await self.bot.db.acquire()
        async with connection.transaction():
            await connection.execute(f"""INSERT INTO scores_settings (guild_id,default_league) VALUES ($1,$2)
                                         ON CONFLICT (guild_id) DO UPDATE SET default_league = $2
                                         WHERE excluded.guild_id = $1""",
                                     ctx.guild.id, None)
        await self.bot.db.release(connection)
        await self.bot.reply(ctx, text='Your commands will no longer use a default league.')

    @commands.command()
    @commands.is_owner()
    async def kill_browser(self, ctx):
        """ Restart browser when you potato. """
        await self.bot.browser.close()
        await self.bot.reply(ctx, "Browser closed.")
        await browser.make_browser(ctx.bot)


def setup(bot):
    """Load the fixtures Cog into the bot"""
    bot.add_cog(Fixtures(bot))
