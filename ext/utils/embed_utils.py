import asyncio
from copy import deepcopy
from io import BytesIO

import aiohttp
import discord
import typing
from PIL import UnidentifiedImageError
from colorthief import ColorThief
import datetime

# Constant, used for footers.
PAGINATION_FOOTER_ICON = "http://pix.iemoji.com/twit33/0056.png"


async def bulk_react(ctx, message, react_list):
    assert ctx.me.permissions_in(ctx.channel).add_reactions
    for r in react_list:
        ctx.bot.loop.create_task(react(message, r))

           
async def react(message, reaction):
    try:
        await message.add_reaction(reaction)
    except (discord.Forbidden, discord.NotFound):
        pass


async def embed_image(ctx, base_embed, image, filename=None):
    if filename is None:
        filename = f"{ctx.message.content}{datetime.datetime.now().ctime()}.png"
    filename = filename.replace('_', '').replace(' ', '').replace(':', '')
    file = discord.File(fp=image, filename=filename)
    base_embed.set_image(url=f"attachment://{filename}")
    await ctx.reply(file=file, embed=base_embed, mention_author=False)

    
async def get_colour(url=None):
    if url is None or url == discord.Embed.Empty:
        return discord.Colour.blurple()
    async with aiohttp.ClientSession() as cs:
        async with cs.get(url) as resp:
            r = await resp.read()
            f = BytesIO(r)
            try:
                loop = asyncio.get_event_loop()
                c = await loop.run_in_executor(None, ColorThief(f).get_color)
                # Convert to base 16 int.
                return int('%02x%02x%02x' % c, 16)
            except UnidentifiedImageError:
                return discord.Colour.blurple()


def rows_to_embeds(base_embed, rows, per_row=10, description_top="") -> typing.List[discord.Embed]:
    pages = [rows[i:i + per_row] for i in range(0, len(rows), per_row)]
    embeds = []
    for page_items in pages:
        base_embed.description = description_top + "\n".join(page_items)
        embeds.append(deepcopy(base_embed))
    return embeds


async def page_selector(ctx, item_list, base_embed=None) -> int or None:
    if len(item_list) == 1:  # Return only item.
        return 0
    
    if base_embed is None:
        base_embed = discord.Embed()
        base_embed.title = "Multiple results found."
        base_embed.set_thumbnail(url=ctx.me.avatar_url)
        base_embed.colour = discord.Colour.blurple()
    
    enumerated = [(enum, item) for enum, item in enumerate(item_list)]
    pages = [enumerated[i:i + 10] for i in range(0, len(enumerated), 10)]
    embeds = []
    for page in pages:
        page_text = "\n".join([f"`[{num}]` {value}" for num, value in page])
        base_embed.description = "Please type matching ID#:\n\n" + page_text
        embeds.append(deepcopy(base_embed))
    try:
        index = await paginate(ctx, embeds, items=item_list, preserve_footer=True)
    except AssertionError:
        return None
    return index


async def paginate(ctx, embeds, preserve_footer=False, items=None, wait_length: int = 60, header="") -> int or None:
    assert len(embeds) > 0, "No results found."
    page = 0
    
    # Add our page number info.
    if len(embeds) > 1:
        for x, y in enumerate(embeds, 1):
            page_line = f"Page {x} of {len(embeds)}"
            if preserve_footer:
                y.add_field(name="Page", value=page_line)
            else:
                y.set_footer(icon_url=PAGINATION_FOOTER_ICON, text=page_line)
                
    if not ctx.me.permissions_in(ctx.channel).add_reactions:
        await ctx.reply("I don't have add_reaction permissions so I can only show you the first page of results.")
        if not items:
            return None
    try:
        m = await ctx.reply(header, embed=embeds[page], mention_author=False)
    except discord.Forbidden:
        try:
            await ctx.reply('I need embed_links permissions to show you these results.')
        except discord.Forbidden:
            await ctx.message.add_reaction('⛔')
        return None
    # Add reaction, we only need "First" and "Last" if there are more than 2 pages.
    reacts = []
    if m is not None:
        try:
            if len(embeds) > 1:
                if len(embeds) > 2:
                    reacts.append("⏮")  # first
                reacts.append("◀")  # prev
                reacts.append("▶")  # next
                if len(embeds) > 2:
                    reacts.append("⏭")  # last
            reacts.append('🚫')
        except (discord.NotFound, discord.Forbidden):
            pass  # Early press or no permissions.
    
    try:
        await bulk_react(ctx, m, reacts)
    except AssertionError:
        reacts = []
    
    # If we're passing an items, we want to get the user's chosen result from the dict.
    # But we always want to be able to change page, or cancel the paginator.

    while not ctx.bot.is_closed():
        waits = []
        if items is not None:
            def id_check(message):
                if not ctx.author.id == message.author.id or not message.content.isdigit():
                    return False
                if int(message.content.strip('[]')) in range(len(items)):
                    return True
        
            waits.append(ctx.bot.wait_for("message", check=id_check))
        if reacts:
            def react_check(r, u):
                if r.message.id == m.id and u.id == ctx.author.id:
                    return str(r.emoji).startswith(tuple(reacts))
        
            waits.append(ctx.bot.wait_for("reaction_add", check=react_check))
            waits.append(ctx.bot.wait_for("reaction_remove", check=react_check))
    
        if not waits:
            return None  # :man_shrugging:
    
        finished, pending = await asyncio.wait(waits, timeout=wait_length, return_when=asyncio.FIRST_COMPLETED)
        
        try:
            result = finished.pop().result()
        except KeyError:  # pop from empty set.
            if items is not None:
                e = m.embeds[0]
                e.title = "Timed out."
                e.colour = discord.Colour.red()
                e.set_footer(text=f"Stopped waiting  response after {wait_length} seconds.")
                try:
                    await m.edit(embed=e, delete_after=10)
                except discord.NotFound:
                    pass  # Why?
            else:
                try:
                    await m.clear_reactions()
                except discord.Forbidden:
                    for i in m.reactions:
                        if i.author == ctx.me:
                            await m.remove_reaction(i, ctx.me)
                except discord.NotFound:
                    pass
            return None
        
        # Kill other.
        for i in pending:
            i.cancel()
        
        if isinstance(result, discord.Message):
            try:
                await m.delete()  # Just a little cleanup.
                await result.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            # We actually return something.
            return int(result.content)
        
        else:  # Reaction.
            # We just want to change page, or cancel.
            if result[0].emoji == "⏮":  # first
                page = 0
                
            elif result[0].emoji == "◀":  # prev
                if page > 0:
                    page += -1
                    
            elif result[0].emoji == "▶":  # next
                if page < len(embeds) - 1:
                    page += 1
                    
            elif result[0].emoji == "⏭":  # last
                page = len(embeds) - 1
                
            elif result[0].emoji == "🚫":  # Delete:
                await m.delete()
                return False
            await m.edit(embed=embeds[page])
