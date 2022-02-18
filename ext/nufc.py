"""Commands specific to the r/NUFC discord"""
import datetime
import random
from collections import defaultdict

from discord import Option, Embed, Colour, ButtonStyle, Interaction, utils, Forbidden, SlashCommandGroup
from discord.ext import commands
from discord.ui import Button, View

# TODO: Permissions Pass.

# Shake meme
SHAKE = ("""Well to start off with anyone who thinks you can trick women into sleeping with you, don't understand game, 
and are generally the ones who embarrass themselves. In a social context women are a lot cleverer then men (in 
general) and understand what's going on when it comes to male female dynamic, that's why you see a lot less 40 year 
old women virgins. \n\nBut just to dispel some myths about \"game\" that are being pushed in this sub. If you 
actually read into game, it's moved on from silly one liners and \"negging\" in the 80's (long before my time) to 
becoming a cool guy who brings value to girls lives around you, by working on yourself and understanding what the 
girl truly wants. Girls want to meet a cool guy \"who understands her\", right? It's more about the vibe and body 
language you give off and \"lines\" are actually pretty heavily advised against. \n\nWhen I said 5/6 I wasn't just 
talking about looks but personality aswell. However if you class judging whether a girl is attractive or not as 
objectifying women, which is what you are implying. then I hate to break it to you but women and in fact everyone 
does this all the time. In fact any man who buys a girl a drink, flowers or a meal is \"objectifying women\". Would 
you buy your friend a meal or flowers? \n\nNearly every women you have encountered (in your demographic), 
even on a subconscious level has judged whether they find you attractive or not (not just your looks), she's probably 
even ranked you compared to other guys she's met. That's just the dynamic between men and women.""")

# Mbemba Generator
MBEMBA = [
    "Matt Ritchie nailing a fan in the balls with a corner flag after a last minute goal against Everton",

    "Director of Football Dennis Wise vetoing a cut-price deal for Bastian Schweinsteiger in favour of loaning a player"
    " he'd seen on YouTube",

    "German international Dietmar Hamann, in his first season at the club, receiving the secret Santa gift of a copy of"
    " Mein Kampf",

    "Alessandro Pistone receiving the secret Santa gift of a sheep's heart because he \"didn't have one of his own\"",

    "Alan Shearer punching, and subsequently knocking out, Keith Gillespie on a club trip to Dublin because Gillespie "
    "dropped some cutlery",

    "Alan Pardew blaming a 2-0 defeat away at Chelsea in August 2012 on the Notting Hill Carnival",

    "Alan Pardew blaming a lack of signings in the summer of 2012 on the idea that too many potential players were busy"
    " watching the Olympics",

    "Ruud Gullit dropping both Alan Shearer and Duncan Ferguson for the Tyne-Wear Derby in favour of Sunderland support"
    "ing Paul Robinson",

    "Joe Kinnear ringing up TalkSport to declare himself Newcastle's new Director of Football and calling our best play"
    "er \"Yohan Kebab\"",

    "Kevin Keegan convincing Rob Lee to join Newcastle by telling him it was closer to London than Middlesbrough is",

    "Shola Ameobi being asked what his teammates call him and replying \"Shola\" then being asked what Sir Bobby calls "
    "him and saying \"Carl Cort\"",

    "Kieron Dyer and Lee Bowyer both being sent off against Aston Villa for fighting each other",
    "Kenny Dalglish selling Les Ferdinand and David Ginola, and replacing them with 35 year old Ian Rush and 33 year ol"
    "d John Barnes",

    "John Barnes being our top scorer with six goals.",
    "Allowing Lomana LuaLua to play against us while he was on loan at Portsmouth. Then him scoring. Then him doing som"
    "ersaults in celebration",

    "that fan punching a police horse",

    "Nobby Solano withholding his number, ringing up Sir Bobby Robson, and playing his trumpet down the phone to him",
    "Spending nearly £6m on Spanish defender Marcelino and him only making 17 appearances over 4 years because of a bro"
    "ken finger",

    "David Ginola being told he couldn't smoke on the team bus because it was unhealthy, just as the bus pulled up to b"
    "uy the squad fish & chips",

    "Daryl Janmaat breaking two fingers by punching a wall because he was angry about being substituted after injuring "
    "his groin",

    "Andy Carroll receiving a court order that forced him to live with Kevin Nolan",

    "Joe Kinnear going on a scouting trip to Birmingham and coming away impressed by Shane Ferguson, who was on loan th"
    "ere from Newcastle",

    "Alan Pardew headbutting David Meyler in the middle of a match against Hull",
    "Lee Clark, then a Sunderland player, turning up at the 1998 FA Cup final between Arsenal and Newcastle in a \"Sad "
    "Mackem BasChampionships\" t-shirt",

    "Clarence Acuna getting pulled over by the police while drunk and dressed as Captain Hook, citing he was too embarr"
    "assed to walk in fancy dress",

    "Faustino Asprilla agreeing to join Newcastle because he was told it was by the sea and assuming it would be full o"
    "f beaches and bikinis",

    "Faustino Asprilla turning up to training 40 mins early rather than his usual 20 mins late because he didn't know t"
    "he clocks had changed",

    "Alan Pardew being given an eight year contract, which still has another three years to run on it - two years after"
    " he left",

    "Kevin Keegan threatening to drop his entire back four of Watson, Peacock, Howey and Beresford after they said they"
    " wanted to play safer",

    "Freddy Shepherd and Douglas Hall being caught calling all female Newcastle supporters \"dogs\"",

    "Yohan Cabaye being denied a visa for a preseason tour of America due to an unpaid dentist bill",

    "Steve McClaren requesting players attend home games in suits so Chancel Mbemba and Florian Thauvin arrived in "
    "tuxedos",

    "When Steven Taylor was shot by a sniper: https://www.youtube.com/watch?v=vl3HnU0HOhk",

    "Selling Andy Carroll for a club record £35m and replacing him days later with 33 year old Shefki Kuqi on a free tr"
    "ansfer",

    "Adjusting our ticketing structure after the fans chanted \"If Sammy Ameobi scores we're on the pitch\". He scored."
    " They went on the pitch",

    "Sammy Ameobi and Demba Ba threatening a noise complaint to a hotel before realising that someone had left a radio "
    "on in their wardrobe",

    "Having a kick-off against Leicester delayed for an hour because our newly installed electronic screen nearly blew"
    " off in the wind",

    "Shola Ameobi ringing the police because of a suspected break in, then cancelling the call out when he realised his"
    " house was just untidy",

    "Patrick Kluivert losing a $4,000 diamond earring in a UEFA Cup match, which was more than our opponents' best paid"
    " player earned a week",

    "At closing time, Faustino Asprilla would often invite entire nightclubs of people back to his house to carry on "
    "partying",

    "Charles N'Zogbia being forced to hand in a transfer request after Joe Kinnear called him \"Charles Insomnia\" in a"
    " post-match interview",

    "Steven Taylor having to have his jaw wired because Andy Carroll punched him and broke it *at the training ground*",

    "NUFC being forced to deny that we were subject to a takeover attempt by WWE owner Vince McMahon",

    "when Laurent Robert decided to do this to Olivier Bernard for reasons unknown. "
    "https://www.youtube.com/watch?v=LltnTI7MzIM",

    "Shay Given being awarded man of the match after we lost 5-1 to Liverpool",

    "Laurent Robert throwing literally all his clothing except his Y-fronts into the crowd In his last match",

    "Shola Ameobi appearing on MTV Cribs, and spending most of his time talking about his coffee table",

    "Temuri Ketsbaia scoring against Bolton and throwing his shirt into the crowd, it not being returned so kicking the"
    " hoardings until it was",

    "Shay Given being the only Irishman who didn't know where Dublin is https://www.youtube.com/watch?v=3Y0kpT_DD6I",

    "John Carver claiming he was the best coach in the Premier League, after winning 9 points from a possible 48",

    "FIFA refusing to allow Hatem Ben Arfa to move to Nice because he made one appearance for Newcastle's reserve side",

    "Barcelona allegedly wanting to sign Steven Taylor, and offering Carles Puyol in exchange",

    "Chancel Mbemba taking to the pitch in the Tyne-Wear derby with \"MBMEMBA\" on the back of his shirt",

    "Newcastle turning down the chance to sign Zinedine Zidane for £1.2m in 1996 by saying he \"wasn't even good enough"
    " to play in Division One\"",

    "Blackburn attempting to get 25 year old Alan Shearer to turn down a move to Newcastle by offering him the role of"
    " player-manager",

    "Kieron Dyer being injured for a month after poking himself in the eye with a pole during training",

    "Andy Carroll being injured for a month after falling off a bar stool",

    "Uruguayans tweeting abuse such as \"Your mother in a thong\" to Paul Dummett after a tackle on Luis Suarez may "
    "have kept him out the World Cup",

    "Joe Kinnear's first official press conference as Newcastle manager beginning with, \"Which one is Simon Bird? "
    "You're a cunt.\"",

    "Winning the Intertoto Cup, only to discover it's less of a cup and more of a certificate "
    "https://www.shelfsidespurs.com/forum/attachments/toto_plaque2_348x470-jpg.2437/",

    "Then assistant manager John Carver going over to the fans after defeat at Southampton and offering to fight them",

    "Jonathan Woodgate smashing a pint glass over his own head while on holiday in Ibiza",

    "Duncan Ferguson trying to buy Nolberto Solano a live llama as a Christmas present, but not finding anybody that "
    "would ship one to Newcastle",

    "Losing the Charity Shield 4-0 against Manchester United, putting out the exact same starting XI for the league "
    "fixture and winning 5-0"
]


# Autocomplete
async def streams(ctx):
    """Return list of live leagues"""
    autocomplete = [i for i in ctx.bot.streams[ctx.interaction.guild.id] if ctx.value.lower() in i.lower()]
    return autocomplete


STREAMS = Option(str, "Remove a stream", autocomplete=streams)
COLOUR = Option(str, "Enter a colour")


class MbembaView(View):
    """Generic View for the Mbemba Generator."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.message = None
        super().__init__()

    async def interaction_check(self, interaction):
        """Assure only person invoking the command can re-roll it."""
        return interaction.user.id == self.ctx.author.id

    async def update(self, content=""):
        """Regenerate the embed and push to view."""
        self.clear_items()
        self.add_item(MbembaButton())

        this = random.choice(MBEMBA)

        e = Embed()
        e.title = "Mbemba when..."
        e.description = f"<:mbemba:332196308825931777> {this}"
        e.colour = Colour.purple()

        if self.message is None:
            self.message = await self.ctx.reply(content=content, embed=e, view=self)
        else:
            await self.message.edit(content=content, embed=e, view=self)


class MbembaButton(Button):
    """Re-roll button"""

    def __init__(self):
        super().__init__(label="Mbemba Again", style=ButtonStyle.blurple, emoji="<:mbemba:332196308825931777>")

    async def callback(self, interaction: Interaction):
        """When clicked, reroll."""
        await interaction.response.defer()
        await self.view.update()


class NUFC(commands.Cog):
    """r/NUFC discord commands"""

    def __init__(self, bot):
        self.bot = bot
        self.bot.streams = defaultdict(dict)

    @commands.slash_command(guild_ids=[332159889587699712])
    async def toon_toon(self, ctx):
        """Toon. Toon, black & white army"""
        return await ctx.reply(content="**BLACK AND WHITE ARMY**")

    @commands.slash_command(guild_ids=[332159889587699712])
    async def mbemba(self, ctx):
        """Mbemba When..."""
        await MbembaView(ctx).update()

    @commands.slash_command(guild_ids=[332159889587699712])
    async def colour(self, ctx, colour: COLOUR):
        """Gives you a colour"""
        if not ctx.channel.permissions_for(ctx.me).manage_roles:
            return await ctx.error('I need manage roles permissions to give you a custom colour.')

        # Get user's old colours.
        remove_list = [i for i in ctx.author.roles if "#" in i.name]

        e = Embed(description=f"Your colour has been updated.")
        colour.strip('#')
        colour = colour.replace('0x', "").upper()

        try:
            d_colo = Colour(int(colour, 16))
        except ValueError:
            view = View()
            btn = Button(style=ButtonStyle.url, url="http://htmlcolorcodes.com/color-picker/", label="Colour picker.")
            view.add_item(btn)
            return await ctx.error('Invalid colour.', view=view)

        # Create new role or fetch if already exists.
        role = utils.get(ctx.guild.roles, name=f"#{colour}")
        if role is None:
            role = await ctx.guild.create_role(name=f"#{colour}", reason=f"Colour for {ctx.author}", color=d_colo)

        await ctx.author.add_roles(role, reason="Apply colour role")
        e.colour = role.color

        # Remove old role.
        await ctx.author.remove_roles(*remove_list)

        # Cleanup old roles.
        for i in remove_list:
            if not i.members:
                await i.delete()

        await ctx.reply(embed=e, ephemeral=True)

    @commands.slash_command(guild_ids=[332159889587699712])
    async def shake(self, ctx):
        """Well to start off with..."""
        await ctx.reply(content=SHAKE)

    streams = SlashCommandGroup("streams", "Stream list for your server")

    @streams.command()
    async def list(self, ctx):
        """List all streams for the match added by users."""
        guild_streams = self.bot.streams[ctx.guild.id]

        if not guild_streams:
            return await ctx.reply(content="Nobody has added any streams yet.")

        e = Embed(title="Streams", description="")
        e.description = ["\n".join(f"{stream} (Added by {added})" for stream, added in guild_streams.items())]
        await ctx.reply(embed=e)

    @streams.command()
    async def add(self, ctx, *, stream):
        """Add a stream to the stream list."""
        guild_streams = self.bot.streams[ctx.guild.id]

        if stream in guild_streams:
            return await ctx.error("Already in stream list.")

        self.bot.streams[ctx.guild.id].update({stream: ctx.author.mention})

        e = Embed(title="Streams", description="")
        e.description = ["\n".join(f"{stream} (Added by {added})" for stream, added in guild_streams.items())]
        await ctx.reply(content=f"Added <{stream}> to stream list.", embed=e)

    @streams.command()
    async def delete(self, ctx, *, stream: STREAMS):
        """Delete a stream from the stream list"""
        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            if not self.bot.streams[ctx.guild.id][stream] == ctx.author.mention:
                err = "You cannot remove a stream you did not add unless you have manage_messages permissions"
                return await ctx.error(err)
        try:
            removed = self.bot.streams[ctx.guild.id].pop(stream)
        except KeyError:
            return await ctx.error(f"Couldn't find that stream in {ctx.guild.name} stream list.")

        await ctx.reply(content=f"<{removed}> removed from streams list.")

    @streams.command()
    async def clear(self, ctx):
        """Remove all streams from guild stream list"""
        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            err = "You cannot remove a stream you did not add unless you have manage_messages permissions"
            return await ctx.error(err)

        self.bot.streams[ctx.guild.id] = []
        await ctx.reply(content="Streams cleared.")

    @commands.slash_command(guild_ids=[332159889587699712])
    async def gherkin(self, ctx):
        """DON'T LET ME GOOOOOO AGAIN"""
        await ctx.reply(content="https://www.youtube.com/watch?v=L4f9Y-KSKJ8")

    @commands.slash_command(guild_ids=[332159889587699712])
    async def radio(self, ctx):
        """Sends a link to the NUFC radio channel"""
        await ctx.reply(content="NUFC Radio Coverage: https://www.nufc.co.uk/liveaudio.html")

    @commands.slash_command(guild_ids=[332159889587699712])
    async def uprafa(self, ctx):
        """Adds an upvote reaction to the last 10 messages"""
        async for message in ctx.channel.history(limit=10):
            await message.add_reaction(":upvote:332196220460072970")

    @commands.slash_command(guild_ids=[332159889587699712])
    async def downrafa(self, ctx):
        """Adds a downvote reaction to the last 10 messages"""
        async for message in ctx.channel.history(limit=10):
            await message.add_reaction(":downvote:332196251959427073")

    @commands.slash_command(guild_ids=[332159889587699712])
    async def roulette(self, ctx):
        """Russian Roulette"""
        x = [False * 5, True]
        outcome = random.choice(x)
        if outcome:
            try:
                await ctx.reply(embed=Embed(title="Timed out for 1 minute."))
                await ctx.author.timeout_for(datetime.timedelta(minutes=1), reason="Roulette")
            except Forbidden:
                await ctx.reply(content="The bullet bounced off your thick fucking skull.")
        else:
            await ctx.reply(content="Click.")


def setup(bot):
    """Load the NUFC Cog into the bot"""
    bot.add_cog(NUFC(bot))
