"""Tracker for the World of Warships Development Blog"""
import datetime
from typing import List, TYPE_CHECKING

from asyncpg import Record
from discord import Interaction, Message, Colour, Embed, HTTPException, TextChannel
from discord.app_commands import Choice, command, autocomplete, describe, default_permissions, guild_only
from discord.ext.commands import Cog
from discord.ext.tasks import loop
from discord.ui import View
from lxml import html
from lxml.html import HtmlElement

from ext.utils.transfer_tools import get_flag
from ext.utils.view_utils import add_page_buttons

if TYPE_CHECKING:
    from painezBot import PBot

SHIP_EMOTES = {'aircarrier': {'normal': '<:aircarrier:991362771662930032>',
                              'premium': '<:aircarrier_premium:991362995424862228>',
                              'special': '<:aircarrier_special:991362955696406578>'},
               'battleship': {'normal': '<:battleship:991360614901493771>',
                              'premium': '<:battleship_premium:991360127707914382>',
                              'special': '<:battleship_special:991359103467274270>'},
               'cruiser': {'normal': '<:Cruiser:991318278611939331>',
                           'premium': '<:cruiser_premium:991360312357953557>',
                           'special': '<:cruiser_special:991356650701205574>'},
               'destroyer': {'normal': '<:Destroyer:991321386532491395>',
                             'premium': '<:destroyer_premium:991360466322460762>',
                             'special': '<:destroyer_special:991359827966173194>'},
               'submarine': {'normal': '<:submarine:991360776763879484>',
                             'premium': '',
                             'special': '<:submarine_special:991360980544143461>'}}


def get_emote(node: HtmlElement):
    """Get the appropriate emote for ship class & rarity combination"""
    s_class = node.attrib.get('data-type', None)

    if s_class is None:
        return ''

    if node.attrib.get('data-premium', None) == 'true':
        return SHIP_EMOTES[s_class]['premium']

    if node.attrib.get('data-special', None) == 'true':
        return SHIP_EMOTES[s_class]['special']

    return SHIP_EMOTES[s_class]['normal']


class DevBlogView(View):
    """Browse Dev Blogs"""

    def __init__(self, bot: 'PBot', interaction: Interaction, pages: List[Record], last: bool = False) -> None:
        super().__init__()
        self.interaction: Interaction = interaction
        self.pages: List[Record] = pages
        self.index: int = len(pages) - 1 if last else 0
        self.bot: PBot = bot

    async def update(self) -> Message:
        """Push the latest version of the view to discord."""
        self.clear_items()
        add_page_buttons(self)
        e = await parse_blog(self.bot, self.pages[self.index]['link'])
        return await self.bot.reply(self.interaction, embed=e, ephemeral=True)


async def parse_blog(bot: 'PBot', url: str):
    """Get Embed from the Dev Blog page"""
    async with bot.session.get(url) as resp:
        tree = html.fromstring(await resp.text())

    article_html = tree.xpath('.//div[@class="article__content"]')[0]

    blog_number = url.split('/')[-1]

    e: Embed = Embed(colour=0x00FFFF, title=''.join(tree.xpath('.//h2[@class="article__title"]/text()')), url=url)
    e.set_author(name=f"World of Warships Development Blog #{blog_number}", url="https://blog.worldofwarships.com/")
    e.timestamp = datetime.datetime.now(datetime.timezone.utc)
    e.set_thumbnail(url="https://cdn.discordapp.com/emojis/814963209978511390.png")
    e.description = ""
    output = []

    def parse(node: HtmlElement):
        """Parse a single node"""

        if node.tag == "img":
            if e.image is None:
                e.set_image(url='http:' + node.attrib['src'])
            return ''

        out = []

        # Nuke excessive whitespace.
        if node.text is not None:
            txt = node.text.strip()
        else:
            txt = None

        match node.tag:
            case 'i':
                if node.attrib.get("class", None) == "superShipStar":
                    out.append(f'\⭐')
                else:
                    print("unhandled 'i' tag", node.attrib['class'], txt)
            case "p":
                if node.getprevious() is not None:
                    out.append('\n')
                out.append(txt)
                if node.getnext() is not None and node.getnext().tag == "p":
                    out.append('\n')
            case "div":
                if node.attrib.get('class', None) == 'article-cut':
                    out.append('\n')
                else:
                    out.append(txt)
            case "ul" | "td" | 'sup':
                out.append(txt)
            case "em":
                # Handle Italics
                out.append(f"*{txt}*")
            case "strong" | "h3" | "h4":
                # Handle Bold.
                # Force line break if this is a standalone bold.
                if txt:
                    out.append(f"**{txt}** ")

                if node.tail == ":":
                    out.append(':')
                    node.tail = None

                if not node.getnext():
                    out.append('\n')
            case "span":
                # Handle Ships
                if node.attrib.get('class', None) == "ship":
                    sub_out = []

                    try:
                        country = node.attrib.get('data-nation', None)
                        if country is not None:
                            sub_out.append(' ' + get_flag(country))
                    except AttributeError:
                        pass

                    try:
                        _class = node.attrib.get('data-type', None)
                        if _class is not None:
                            sub_out.append(get_emote(node))
                    except AttributeError:
                        pass

                    if txt is not None:
                        sub_out.append(f"**{txt}** ")
                    out.append(' '.join(sub_out))

                else:
                    out.append(txt)
            case "li":
                out.append('\n')
                if node.text:
                    match node.getparent().getparent().tag:
                        case "ul" | "ol" | "li":
                            out.append(f"∟○ {txt}")
                        case _:
                            out.append(f"• {txt}")

                if node.getnext() is None:
                    if len(node) == 0:  # Number of children
                        out.append('\n')
            case "a":
                out.append(f"[{txt}]({node.attrib['href']})")
            case _:
                print(f"Unhandled node tag found: {node.tag} | {txt} | {node.tail}")
                out.append(txt)

        for sub_node in node.iterchildren():
            out.append(parse(sub_node))

        if node.tail:
            tail = node.tail.strip() + ' '

            match node.getparent().tag:
                case "span":
                    # Handle Ships
                    if node.getparent().attrib.get('class', None) == "ship":
                        out.append(f'**{tail}**')
                    else:
                        out.append(tail)
                case 'em':
                    out.append(f'*{tail}*')
                case _:
                    out.append(tail)

        return ''.join([i for i in out if i])

    for elem in article_html.iterchildren():
        output.append(parse(elem))

    output = ''.join(output)
    if len(output) > 4000:
        trunc = f"…\n[Read Full Article]({url})"
        e.description = output.ljust(4000)[:4000 - len(trunc)] + trunc
    else:
        e.description = output
    return e


async def db_ac(interaction: Interaction, current: str) -> List[Choice]:
    """Autocomplete dev blog by text"""
    cache = getattr(interaction.client, 'dev_blog_cache', [])
    blogs = [i for i in cache if current.lower() in f"{i['title']} {i['text']}".lower()]
    choices = [Choice(name=f"{i['id']}: {i['title']}"[:100], value=str(i['id'])) for i in blogs]
    return choices[:-25:-1]  # Last 25 items reversed


class DevBlog(Cog):
    """DevBlog Commands"""

    def __init__(self, bot: 'PBot'):
        self.bot: PBot = bot
        self.bot.dev_blog = self.blog_loop.start()

        # Dev Blog Cache
        self.bot.dev_blog_cache = []
        self.bot.dev_blog_channels = []

    async def cog_load(self) -> None:
        """Do this on Cog Load"""
        await self.update_cache()
        await self.get_blogs()

    async def cog_unload(self) -> None:
        """Stop previous runs of tickers upon Cog Reload"""
        self.bot.dev_blog.cancel()

    @loop(seconds=60)
    async def blog_loop(self) -> None:
        """Loop to get the latest dev blog articles"""
        if self.bot.session is None or not self.bot.dev_blog_cache:
            return

        async with self.bot.session.get('https://blog.worldofwarships.com/rss-en.xml') as resp:
            tree = html.fromstring(bytes(await resp.text(), encoding='utf8'))

        articles = tree.xpath('.//item')
        for i in articles:
            link = ''.join(i.xpath('.//guid/text()'))
            if ".ru" in link:
                continue

            blog_id = int(link.split('/')[-1])
            if blog_id in [r['id'] for r in self.bot.dev_blog_cache]:
                continue

            await self.store_blog(blog_id)
            await self.get_blogs()

            e = await parse_blog(self.bot, link)

            for x in self.bot.dev_blog_channels:
                ch = self.bot.get_channel(x)
                try:
                    await ch.send(embed=e)
                except HTTPException:
                    continue
        self.bot.dev_dev_blog_cached = True

    @blog_loop.before_loop
    async def pre_blog(self) -> None:
        """Assure dev blog channel list is loaded."""
        await self.update_cache()

    async def get_blogs(self) -> None:
        """Get a list of old dev blogs stored in DB"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """SELECT * FROM dev_blogs"""
                self.bot.dev_blog_cache = await connection.fetch(q)
        finally:
            await self.bot.db.release(connection)

    async def store_blog(self, blog_id: int) -> None:
        """Get the inner text of a specific dev blog"""
        if blog_id in [r['id'] for r in self.bot.dev_blog_cache]:
            return

        url = f"https://blog.worldofwarships.com/blog/{blog_id}"

        async with self.bot.session.get(url) as resp:
            src = await resp.text()

        tree = html.fromstring(src)
        try:
            title = str(tree.xpath('.//title/text()')[0])
            title = title.split(' - Development')[0]
        except IndexError:
            print("Could not find Title for blog #", blog_id)
            return

        text = tree.xpath('.//div[@class="article__content"]')[0].text_content()

        if text:
            print("Storing Dev Blog #", blog_id)
        else:
            print("Could not find content for blog #", blog_id)
            return

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                q = """INSERT INTO dev_blogs (id, title, text) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING"""
                await connection.execute(q, blog_id, title, text)
        finally:
            await self.bot.db.release(connection)

    @command()
    @guild_only()
    @default_permissions(manage_channels=True)
    async def blog_tracker(self, interaction: Interaction) -> Message:
        """Enable/Disable the World of Warships dev blog tracker in this channel."""
        await interaction.response.defer(thinking=True)
        if interaction.channel.id in self.bot.dev_blog_channels:
            q = """DELETE FROM dev_blog_channels WHERE channel_id = $1"""
            args = [interaction.channel.id]
            output = "New Dev Blogs will no longer be sent to this channel."
            colour = Colour.red()
        else:
            q = """INSERT INTO dev_blog_channels (channel_id, guild_id) VALUES ($1, $2)"""
            args = [interaction.channel.id, interaction.guild.id]
            output = "new Dev Blogs will now be sent to this channel."
            colour = Colour.green()

        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, *args)
        finally:
            await self.bot.db.release(connection)

        await self.update_cache()

        e = Embed(colour=colour, title="Dev Blog Tracker", description=output)
        e.set_author(icon_url=self.bot.user.display_avatar.url, name=self.bot.user.name)
        return await self.bot.reply(interaction, embed=e)

    async def update_cache(self) -> None:
        """Get a list of channels to send dev blogs to"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                channels = await connection.fetch("""SELECT * FROM dev_blog_channels""")
                self.bot.dev_blog_channels = [r['channel_id'] for r in channels]
        finally:
            await self.bot.db.release(connection)

    @command()
    @autocomplete(search=db_ac)
    @describe(search="Search for a dev blog by text content")
    async def devblog(self, interaction: Interaction, search: str) -> Message:
        """Fetch a World of Warships dev blog, either search for text or leave blank to get latest."""
        await interaction.response.defer()

        try:
            int(search)
            e = await parse_blog(self.bot, f"https://blog.worldofwarships.com/blog/{search}")
            return await self.bot.reply(interaction, embed=e, ephemeral=True)
        except ValueError:
            # If a specific blog is not selected, send the browser view.
            s = search.lower()
            matches = [i for i in self.bot.dev_blog_cache if s in f"{i['title'].lower()}{i['text'].lower()}"]
            view = DevBlogView(self.bot, interaction, pages=matches)
            return await view.update()

    @Cog.listener()
    async def on_guild_channel_delete(self, channel: TextChannel) -> None:
        """Remove dev blog trackers from deleted channels"""
        q = f"""DELETE FROM dev_blog_channels WHERE channel_id = $1"""
        connection = await self.bot.db.acquire()
        try:
            async with connection.transaction():
                await connection.execute(q, channel.id)
        finally:
            await self.bot.db.release(connection)


async def setup(bot: 'PBot') -> None:
    """Load the Dev Blog Cog into the bot."""
    await bot.add_cog(DevBlog(bot))
