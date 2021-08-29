"""Custom Utilities revolving around the usage of Discord Embeds"""
import asyncio
import typing
from copy import deepcopy
from io import BytesIO

import aiohttp
import discord
from PIL import UnidentifiedImageError
from colorthief import ColorThief

PAGINATION_FOOTER_ICON = "http://pix.iemoji.com/twit33/0056.png"


async def bulk_react(ctx, message, react_list):
    """Spooler to send multiple reactions to a message object"""
    assert ctx.channel.permissions_for(ctx.me).add_reactions
    for r in react_list:
        ctx.bot.loop.create_task(react(message, r))


async def react(message, reaction):
    """Send a single reaction to a message object"""
    try:
        await message.add_reaction(reaction)
    except discord.HTTPException:
        pass


async def embed_image(ctx, base_embed, image, filename=None):
    """Utility / Shortcut to upload image & set it within an embed."""
    if filename is None:
        filename = f"{ctx.command}.png"
    filename = filename.replace('_', '').replace(' ', '').replace(':', '')
    base_embed.set_image(url=f"attachment://{filename}")
    await ctx.bot.reply(ctx, image=image, filename=filename, embed=base_embed)


async def get_colour(url=None):
    """Use colour thief to grab a sampled colour from an image for an Embed"""
    if url is None or url == discord.Embed.Empty:
        return discord.Colour.og_blurple()
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
                return discord.Colour.og_blurple()


def rows_to_embeds(base_embed, rows, rows_per=10, header="", footer="") -> typing.List[discord.Embed]:
    """Create evenly distributed rows of text from a list of data"""
    desc, count = header + "\n", 0
    embeds = []
    for row in rows:
        if len(desc + footer + row) <= 4096 and (count + 1 <= rows_per if rows_per is not None else True):
            desc += f"{row}\n"
            count += 1
        else:
            desc += footer
            base_embed.description = desc
            embeds.append(deepcopy(base_embed))
            desc, count = f"{header}\n{row}\n", 0

    desc += footer
    base_embed.description = desc
    embeds.append(deepcopy(base_embed))
    return embeds


async def page_selector(ctx, item_list, base_embed=None, choice_text=None,
                        preserve_footer=True, confirm_single=False) -> int:
    """Embed UI for user to select from a list of items"""
    if len(item_list) == 1:  # Return only item.
        if confirm_single is False:
            return 0

    if base_embed is None:
        base_embed = discord.Embed()
        base_embed.title = "Multiple results found."
        base_embed.set_thumbnail(url=ctx.me.display_avatar.url)
        base_embed.colour = discord.Colour.og_blurple()
    
    base_embed.add_field(name="Type the matching number for your choice",
                         value="```fix\nE.g. type 0 to select the item marked with [0]```",
                         inline=False)
    
    choice_text = "Please type matching ID#:" if choice_text is None else choice_text
    
    enumerated = [(enum, item) for enum, item in enumerate(item_list)]
    pages = [enumerated[i:i + 10] for i in range(0, len(enumerated), 10)]
    embeds = []
    for page in pages:
        page_text = "\n".join([f"`[{num}]` {value}" for num, value in page])
        base_embed.description = f"{choice_text}\n\n" + page_text
        embeds.append(deepcopy(base_embed))

    try:
        index = await paginate(ctx, embeds, items=item_list, preserve_footer=preserve_footer)
    except AssertionError:
        return -1

    return index


async def paginate(ctx, embeds, preserve_footer=False, items=None, wait_length: int = 60, header="") -> int or None:
    """Graphical UI for user to page through multiple embeds using reactions"""
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
    
        # Warn about permisssions.
        perms = ctx.channel.permissions_for(ctx.me)
        if not perms.add_reactions and perms.send_messages:
            await ctx.bot.reply(ctx, text="I don't have add_reaction permissions so I can only show you page 1.")
            if not items:
                return None

    m = await ctx.bot.reply(ctx, text=header, embed=embeds[page])

    # Add reaction, we only need "First" and "Last" if there are more than 2 pages.
    reacts = []
    if m is not None:
        if len(embeds) > 1:
            if len(embeds) > 2:
                reacts.append("⏮")  # first
            reacts.append("◀")  # prev
            reacts.append("▶")  # next
            if len(embeds) > 2:
                reacts.append("⏭")  # last
        reacts.append('🚫')
    
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
                """Verify the reaction came from the invoker of the paginator"""
                if not ctx.author.id == message.author.id or not message.content.isdecimal():
                    return False
                try:
                    val = int(message.content.strip('[]'))
                    return val in range(len(items))
                except ValueError:
                    return False
        
            waits.append(ctx.bot.wait_for("message", check=id_check))
        if reacts:
            def react_check(r, u):
                """Verify a reaction came from the invoker of the paginator"""
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
                e.set_footer(text=f"Stopped waiting for response after {wait_length} seconds.")
                try:
                    await m.edit(embed=e, allowed_mentions=discord.AllowedMentions().none())
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
                if m is not None:
                    await m.delete()  # Just a little cleanup.
                await result.delete()
            except discord.HTTPException:
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
                return -1
            await m.edit(embed=embeds[page], allowed_mentions=discord.AllowedMentions().none())
