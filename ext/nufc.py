"""Commands specific to the r/NUFC discord"""
from __future__ import annotations

import datetime
import logging
import random

from typing import TYPE_CHECKING, TypeAlias
import typing

import discord
from discord.ui import Button, View
from discord.ext import commands, tasks

from ext.logs import stringify_seconds
from ext.utils.view_utils import BaseView

if TYPE_CHECKING:
    from core import Bot

    Interaction: TypeAlias = discord.Interaction[Bot]

logger = logging.getLogger("nufc")

CLR_PICKER = "http://htmlcolorcodes.com/color-picker/"
M_EMOJI = "<:mbemba:332196308825931777>"

# Shake meme
SHAKE = (
    "Well to start off with anyone who thinks you can trick women into"
    "sleeping with you, don't understand game, and are generally the "
    "ones who embarrass themselves. In a social context women are a lot"
    " cleverer then men (in general) and understand what's going on when"
    "it comes to male female dynamic, that's why you see a lot less 40 "
    "year old women virgins. \n\nBut just to dispel some myths about "
    '"game" that are being pushed in this sub. If you actually read'
    ' into game, it\'s moved on from silly one liners and "negging" '
    "in the 80's (long before my time) to becoming a cool guy who brings"
    " value to girls lives around you, by working on yourself and"
    " understanding what the girl truly wants. Girls want to meet a cool"
    ' guy "who understands her", right? It\'s more about the vibe and'
    ' body language you give off and "lines" are actually pretty heavily'
    " advised against. \n\nWhen I said 5/6 I wasn't just talking about"
    " looks but personality aswell. However if you class judging whether"
    " a girl is attractive or not as objectifying women, which is what"
    " you are implying. then I hate to break it to you but women and in"
    " fact everyone does this all the time. In fact any man who buys a"
    ' girl a drink, flowers or a meal is "objectifying women". Would'
    " you buy your friend a meal or flowers? \n\nNearly every women you"
    " have encountered (in your demographic), even on a subconscious level"
    " has judged whether they find you attractive or not (not just your"
    " looks), she's probably even ranked you compared to other guys she's"
    " met. That's just the dynamic between men and women."
)
# Mbemba Generator
MBEMBA = [
    "Matt Ritchie nailing a fan in the balls with a corner flag after a last"
    " minute goal against Everton",
    "Director of Football Dennis Wise vetoing a cut-price deal for Bastian"
    " Schweinsteiger in favour of loaning a player"
    " he'd seen on YouTube",
    "German international Dietmar Hamann, in his first season at the club,"
    "receiving the secret Santa gift of a copy of Mein Kampf",
    "Alessandro Pistone receiving the secret Santa gift of a sheep's heart"
    'because he "didn\'t have one of his own"',
    "Alan Shearer punching, and subsequently knocking out, Keith Gillespie"
    "on a club trip to Dublin because Gillespie dropped some cutlery",
    "Alan Pardew blaming a 2-0 defeat away at Chelsea in August 2012 on the"
    "Notting Hill Carnival",
    "Alan Pardew blaming a lack of signings in the summer of 2012 on the idea"
    " that too many potential players were busy watching the Olympics",
    "Ruud Gullit dropping both Alan Shearer and Duncan Ferguson for the"
    " Tyne-Wear Derby in favour of Sunderland supporting Paul Robinson",
    "Joe Kinnear ringing up TalkSport to declare himself Newcastle's new"
    ' Director of Football and calling our best player "Yohan Kebab"',
    "Kevin Keegan convincing Rob Lee to join Newcastle by telling him it was"
    " closer to London than Middlesbrough is",
    'Shola Ameobi being asked what his teammates call him and replying "Shola"'
    ' then being asked what Sir Bobby calls him and saying "Carl Cort"',
    "Kieron Dyer and Lee Bowyer both being sent off against Aston Villa for"
    "fighting each other",
    "Kenny Dalglish selling Les Ferdinand and David Ginola, and replacing them"
    "with 35 year old Ian Rush and 33 year old John Barnes",
    "John Barnes being our top scorer with six goals.",
    "Allowing Lomana LuaLua to play against us while he was on loan at"
    " Portsmouth. Then him scoring. Then him doing somersaults in celebration",
    "that fan punching a police horse",
    "Nobby Solano withholding his number, ringing up Sir Bobby Robson, and"
    "playing his trumpet down the phone to him",
    "Spending nearly £6m on Spanish defender Marcelino and him only making 17"
    "appearances over 4 years because of a broken finger",
    "David Ginola being told he couldn't smoke on the team bus because it was"
    "unhealthy, just as the bus pulled up to buy the squad fish & chips",
    "Daryl Janmaat breaking two fingers by punching a wall because he was"
    "angry about being substituted after injuring his groin",
    "Andy Carroll receiving a court order that forced him to live with"
    "Kevin Nolan",
    "Joe Kinnear going on a scouting trip to Birmingham and coming away"
    "impressed by Shane Ferguson, who was on loan there from Newcastle",
    "Alan Pardew headbutting David Meyler in the middle of a match against"
    " Hull",
    "Lee Clark, then a Sunderland player, turning up at the 1998 FA Cup final"
    'between Arsenal and Newcastle in a "Sad Mackem BasChampionships" t-shirt',
    "Clarence Acuna getting pulled over by the police while drunk and dressed"
    "as Captain Hook, citing he was too embarrassed to walk in fancy dress",
    "Faustino Asprilla agreeing to join Newcastle because he was told it was"
    "by the sea and assuming it would be full of beaches and bikinis",
    "Faustino Asprilla turning up to training 40 mins early rather than his"
    "usual 20 mins late because he didn't know the clocks had changed",
    "Alan Pardew being given an 8 year contract, ending 5 years after he left",
    "Kevin Keegan threatening to drop his entire back four of Watson, Peacock"
    "Howey and Beresford after they said they wanted to play safer",
    "Freddy Shepherd and Douglas Hall being caught calling all female"
    ' Newcastle supporters "dogs"',
    "Yohan Cabaye being denied a visa for a preseason tour of America due to"
    " an unpaid dentist bill",
    "Steve McClaren requesting players attend home games in suits so Chancel"
    "Mbemba and Florian Thauvin arrived in tuxedos",
    "When Steven Taylor was shot by a sniper: "
    "https://www.youtube.com/watch?v=vl3HnU0HOhk",
    "Selling Andy Carroll for a club record £35m and replacing him days later"
    "with 33 year old Shefki Kuqi on a free transfer",
    'Adjusting our ticketing structure after the fans chanted "If Sammy '
    "scores we're on the pitch\". He scored. They went on the pitch",
    "Sammy Ameobi and Demba Ba threatening a noise complaint to a hotel before"
    "realising that someone had left a radio on in their wardrobe",
    "Having a kick-off against Leicester delayed for an hour because our newly"
    " installed electronic screen nearly blew off in the wind",
    "Shola Ameobi ringing the police because of a suspected break in, then"
    " cancelling the call out when he realised his house was just untidy",
    "Patrick Kluivert losing a $4,000 diamond earring in a UEFA Cup match,"
    " which was more than our opponents' best paid player earned a week",
    "At closing time, Faustino Asprilla would often invite entire nightclubs "
    "of people back to his house to carry on partying",
    "Charles N'Zogbia being forced to hand in a transfer request after Joe "
    'Kinnear called him "Charles Insomnia" in a post-match interview',
    "Steven Taylor having to have his jaw wired because Andy Carroll punched"
    " him and broke it *at the training ground*",
    "NUFC being forced to deny that we were subject to a takeover attempt"
    " by WWE owner Vince McMahon",
    "when Laurent Robert decided to do this to Olivier Bernard for reasons"
    " unknown. https://www.youtube.com/watch?v=LltnTI7MzIM",
    "Shay Given being awarded man of the match after we lost 5-1 to Liverpool",
    "Laurent Robert throwing literally all his clothing except his Y-fronts"
    "into the crowd In his last match",
    "Shola Ameobi appearing on MTV Cribs, and spending most of his time "
    "talking about his coffee table",
    "Temuri Ketsbaia scoring against Bolton and throwing his shirt into the"
    " crowd, it not being returned so kicking the hoardings until it was",
    "Shay Given being the only Irishman who didn't know where Dublin is "
    "https://www.youtube.com/watch?v=3Y0kpT_DD6I",
    "John Carver claiming he was the best coach in the Premier League, after"
    " 9 points in 16 games",
    "FIFA refusing to allow Hatem Ben Arfa to move to Nice because he made one"
    " appearance for Newcastle's reserve side",
    "Barcelona allegedly wanting to sign Steven Taylor, and offering Carles"
    " Puyol in exchange",
    'Chancel Mbemba taking to the pitch in the Tyne-Wear derby with "MBMEMBA"'
    " on the back of his shirt",
    "Newcastle turning down the chance to sign Zinedine Zidane for £1.2m in"
    ' 1996 by saying he "wasn\'t even good enough" to play in Division One',
    "Blackburn attempting to get 25 year old Alan Shearer to turn down a move"
    " to Newcastle by offering him the role of player-manager",
    "Kieron Dyer being injured for a month after poking himself in the eye"
    " with a pole during training",
    "Andy Carroll being injured for a month after falling off a bar stool",
    'Uruguayans tweeting abuse such as "Your mother in a thong" to Paul Dum'
    "mett after a tackle on Luis Suarez may have kept him out the World Cup",
    "Joe Kinnear's first official press conference as Newcastle manager "
    'beginning with, "Which one is Simon Bird? You\'re a cunt."',
    "Winning the Intertoto Cup, only to discover it's less of a cup and more"
    " of a certificate https://www.shelfsidespurs.com/forum/attachments/toto"
    "_plaque2_348x470-jpg.2437/",
    "Then assistant manager John Carver going over to the fans after defeat at"
    " Southampton and offering to fight them",
    "Jonathan Woodgate smashing a pint glass over his own head while on"
    " holiday in Ibiza",
    "Duncan Ferguson trying to buy Nolberto Solano a live llama as a Christmas"
    " present, but not finding anybody that would ship one to Newcastle",
    "Losing the Charity Shield 4-0 against Manchester United, putting out the"
    " exact same starting XI for the league fixture and winning 5-0",
]


class MbembaView(BaseView):
    """Generic View for the Mbemba Generator."""

    def __init__(self, interaction: Interaction):
        super().__init__(interaction.user, parent=None)

    def generate(self) -> discord.Embed:
        """Generate a Mbemba Embed"""
        item = random.choice(MBEMBA)
        embed = discord.Embed()
        embed.colour = discord.Colour.purple()
        embed.description = f"<:mbemba:332196308825931777> {item}"
        return embed

    async def update(self, interaction: Interaction) -> None:
        """Regenerate the embed and push to view."""
        embed = self.generate()
        return await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.blurple, emoji=M_EMOJI)
    async def again(self, interaction: Interaction, _) -> None:
        """When clicked, re roll."""
        await self.update(interaction)


class NUFC(commands.Cog):
    """r/NUFC discord commands"""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.vanity_snipe.start()

    @tasks.loop(minutes=10)
    async def vanity_snipe(self) -> None:
        nufc_guild = self.bot.get_guild(332159889587699712)
        if nufc_guild is None:
            return

        try:
            await nufc_guild.edit(vanity_code="nufc")
        except discord.HTTPException:
            return

        channel = self.bot.get_channel(332167195339522048)
        if isinstance(channel, discord.TextChannel):
            await channel.send("@everyone http://discord.gg/nufc Sniped.")

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    async def mbemba(self, interaction: Interaction) -> None:
        """Mbemba When…"""
        mbm_view = MbembaView(interaction)
        embed = mbm_view.generate()
        await interaction.response.send_message(view=mbm_view, embed=embed)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    @discord.app_commands.describe(hex_code="Enter a colour #hexcode")
    @discord.app_commands.default_permissions(change_nickname=True)
    async def colour(self, interaction: Interaction, hex_code: str) -> None:
        """Gives you a colour"""
        # Get user's old colours.
        guild = interaction.guild
        if guild is None:
            return

        member = typing.cast(discord.Member, interaction.user)

        embed = discord.Embed(description="Your colour has been updated.")
        try:
            code = hex_code.strip("#").replace("0x", "").upper()
            d_colo = discord.Colour(int(code, 16))
        except ValueError:
            view = View()
            btn: Button[View] = Button(url=CLR_PICKER, label="Colour picker.")
            view.add_item(btn)
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "🚫 Invalid Colourr"
            reply = interaction.response.send_message
            return await reply(embed=embed, ephemeral=True, view=view)

        role = discord.utils.get(guild.roles, name=f"#{hex_code}")
        if role is None:  # Create new role or fetch if already exists.
            role = await guild.create_role(
                name=f"#{hex_code}",
                reason=f"Colour for {interaction.user}",
                color=d_colo,
            )

        await member.add_roles(role, reason="Apply colour role")
        embed.colour = role.color

        # Remove old role.
        remove_list = [i for i in member.roles if i.name.startswith("#")]
        await member.remove_roles(*remove_list)

        # Cleanup old roles.
        for i in remove_list:
            if not i.members:
                await i.delete()
        return await interaction.response.send_message(embed=embed)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    async def shake(self, interaction: Interaction) -> None:
        """Well to start off with…"""
        return await interaction.response.send_message(content=SHAKE)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    async def gherkin(self, interaction: Interaction) -> None:
        """DON'T LET ME GOOOOOO AGAIN"""
        url = "https://www.youtube.com/watch?v=L4f9Y-KSKJ8"
        return await interaction.response.send_message(url)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    async def radio(self, interaction: Interaction) -> None:
        """Sends a link to the NUFC radio channel"""
        text = "Radio Coverage: https://www.nufc.co.uk/liveaudio.html"
        return await interaction.response.send_message(text)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    async def downhowe(self, interaction: Interaction) -> None:
        """Adds a downvote reaction to the last 10 messages"""
        await interaction.response.defer(thinking=True)
        channel = typing.cast(discord.TextChannel, interaction.channel)
        try:
            async for message in channel.history(limit=10):
                await message.add_reaction(":downvote:332196251959427073")
        except discord.Forbidden:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "❌ I can't react in this channel"
            await interaction.response.send_message(embed=embed)
            return
        txt = ":downvote:332196251959427073"
        await interaction.edit_original_response(content=txt)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    async def uphowe(self, interaction: Interaction) -> None:
        """Adds an upvote reaction to the last 10 messages"""
        await interaction.response.defer(thinking=True)
        channel = typing.cast(discord.TextChannel, interaction.channel)
        try:
            async for message in channel.history(limit=10):
                await message.add_reaction(":upvote:332196220460072970")
        except discord.Forbidden:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "❌ I can't react in this channel"
            await interaction.followup.send(embed=embed)
            return
        txt = ":upvote:332196220460072970"
        await interaction.edit_original_response(content=txt)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    async def toon_toon(self, interaction: Interaction) -> None:
        """Toon. Toon, black & white army"""
        text = "**BLACK AND WHITE ARMY**"
        return await interaction.response.send_message(text)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    async def goala(self, interaction: Interaction) -> None:
        """Party on Garth"""
        file = discord.File(fp="Images/goala.gif")
        return await interaction.response.send_message(file=file)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    async def ructions(self, interaction: Interaction) -> None:
        """WEW. RUCTIONS."""
        file = discord.File(fp="Images/ructions.png")
        return await interaction.response.send_message(file=file)

    @discord.app_commands.command()
    @discord.app_commands.guilds(332159889587699712)
    @discord.app_commands.describe(timeout="Timeout duration if you lose")
    async def roulette(
        self, interaction: Interaction, timeout: int = 60
    ) -> None:
        """Russian Roulette"""
        if isinstance(interaction.user, discord.User):
            raise commands.NoPrivateMessage

        if random.choice([False * 5, True]):
            embed = discord.Embed(colour=discord.Colour.red(), title="Bang")

            time = datetime.timedelta(seconds=timeout)
            try:
                await interaction.user.timeout(time, reason="Roulette")
                secs = stringify_seconds(timeout)
                embed.description = f"Timed out for {secs}"
            except discord.Forbidden:
                embed.description = "The bullet bounced off your thick skull."
                embed.set_footer(text="I can't time you out")
        else:
            embed = discord.Embed(title="Click", colour=discord.Colour.green())
            embed.description = f"{stringify_seconds(timeout)} timeout avoided"
        return await interaction.response.send_message(embed=embed)


async def setup(bot: Bot) -> None:
    """Load the NUFC Cog into the bot"""
    await bot.add_cog(NUFC(bot))
