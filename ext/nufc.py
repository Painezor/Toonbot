"""Commands specific to the r/NUFC discord"""
import random

import discord
from discord.ext import commands


class NUFC(commands.Cog):
    """r/NUFC discord commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.emoji = "👕"
        self.bot.streams = {}
        with open('girls_names.txt', "r") as f:
            self.girls = f.read().splitlines()
    
    def cog_check(self, ctx):
        """Assure all commands in this cog can only be ran on the r/NUFC discord"""
        if ctx.guild:
            return ctx.guild.id in [238704683340922882, 332159889587699712]

    @commands.Cog.listener()
    async def on_message(self, m):
        """On message reactions specific to the r/NUFC discord"""
        c = m.content.lower()
        if "toon toon" in c:
            try:
                await m.channel.send("**BLACK AND WHITE ARMY**")
            except discord.HTTPException:
                pass
            return

        if not m.guild or not m.guild.id == 332159889587699712:
            return
        
        # ignore bot messages
        if m.author.bot:
            return

        autokicks = ["make me a mod", "make me mod", "give me mod"]
        for i in autokicks:
            if i in c:
                try:
                    await m.author.kick(reason="Asked to be made a mod.")
                except discord.Forbidden:
                    return await m.channel.send(f"Done. {m.author.mention} is now a moderator.")
                await m.channel.send(f"{m.author} was auto-kicked.")
        if "https://www.reddit.com/r/" in c and "/comments/" in c:
            if "nufc" not in c:
                rm = "*Reminder: Please do not vote on submissions or comments in other subreddits.*"
                await m.channel.send(rm)
                
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Bully kegs with a random girl's name."""
        if member.id == 272722118192529409:
            await member.edit(nick=random.choice(self.girls).title())
    
    @commands.command(aliases=["color"], hidden=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def colour(self, ctx, colour):
        """Gives you a colour"""
        colour.strip('#')
        colour.strip('0x')
        colour = colour.upper()
        
        try:
            d_colo = discord.Colour(int(colour, 16))
        except ValueError:
            return await self.bot.reply(ctx, 'Invalid colour. Check <http://htmlcolorcodes.com/color-picker/>',
                                        ping=True)
        
        e = discord.Embed(color=d_colo)
        e.description = f"Your colour has been updated."
        
        remove_list = [i for i in ctx.author.roles if "#" in i.name]
        await ctx.author.remove_roles(*remove_list)
        
        for i in remove_list:
            if not i.members:
                await i.delete()
        
        if discord.utils.get(ctx.guild.roles, name=f"#{colour}") is None:
            try:
                role = await ctx.guild.create_role(name=f"#{colour}", reason=f"Colour for {ctx.author}", color=d_colo)
            except discord.HTTPException:
                return await self.bot.reply(ctx, "Invalid colour specified.")
        else:
            role = discord.utils.get(ctx.guild.roles, name=f"#{colour}")
        
        await ctx.author.add_roles(role, reason="Apply colour role")
        await self.bot.reply(ctx, embed=e)
    
    @commands.command(hidden=True)
    @commands.is_owner()
    async def shake(self, ctx):
        """Well to start off with..."""
        await self.bot.reply(ctx,
                             text="Well to start off with anyone who thinks you can trick women into sleeping with "
                                  "you, don't understand"
                                  " game, and are generally the ones who embarrass themselves. In a social context "
                                  "women are a lot cleverer "
                                  "then men (in general) and understand what's going on when it comes to male female "
                                  "dynamic, that's why you "
                                  "see a lot less 40 year old women virgins. \n\nBut just to dispel some myths about "
                                  "\"game\" that are being "
                                  "pushed in this sub. If you actually read into game, it's moved on from silly one "
                                  "liners and \"negging\" "
                                  "in the 80's (long before my time) to becoming a cool guy who brings value to girls "
                                  "lives around you, "
                                  "by working on yourself and understanding what the girl truly wants. Girls want to "
                                  "meet a cool guy \"who "
                                  "understands her\", right? It's more about the vibe and body language you give off "
                                  "and \"lines\" are "
                                  "actually pretty heavily advised against. \n\nWhen I said 5/6 I wasn't just talking "
                                  "about looks but "
                                  "personality aswell. However if you class judging whether a girl is attractive or "
                                  "not as objectifying "
                                  "women, which is what you are implying. then I hate to break it to you but women "
                                  "and "
                                  "in fact everyone does "
                                  "this all the time. In fact any man who buys a girl a drink, flowers or a meal is "
                                  "\"objectifying women\". "
                                  "Would you buy your friend a meal or flowers? \n\nNearly every women you have "
                                  "encountered (in your "
                                  "demographic), even on a subconscious level has judged whether they find you "
                                  "attractive or not (not just "
                                  "your looks), she's probably even ranked you compared to other guys she's met. "
                                  "That's just the dynamic "
                                  "between men and women.")
    
    @commands.group(invoke_without_command=True, aliases=["stream"], hidden=True)
    async def streams(self, ctx):
        """List alls for the match added by users."""
        try:
            if not self.bot.streams[f"{ctx.guild.id}"]:
                return await self.bot.reply(ctx, text="Nobody has added any streams yet.")
        except KeyError:
            self.bot.streams[f"{ctx.guild.id}"] = []
            return await self.bot.reply(ctx, text="Nobody has added any streams yet.")
        output = "**Streams: **\n"
        for c, v in enumerate(self.bot.streams[f"{ctx.guild.id}"], 1):
            output += f"{c}: {v}\n"
        await self.bot.reply(ctx, text=output)
    
    @streams.command(name="add")
    async def stream_add(self, ctx, *, stream):
        """Add a stream to the stream list."""
        stream = discord.utils.escape_mentions(stream)
        if "://" not in stream:
            return await self.bot.reply(ctx, text="That doesn't look like a valid URL.")
        # Hide link preview.
        if "http" in stream:
            stream = f"<{stream}>"
        
        # Check for dupes.
        try:
            for i in self.bot.streams[f"{ctx.guild.id}"]:
                if stream in i:
                    return await self.bot.reply(ctx, text="Already in stream list.")
        except KeyError:
            self.bot.streams[f"{ctx.guild.id}"] = [stream]
        else:
            self.bot.streams[f"{ctx.guild.id}"].append(f"{stream} (added by {ctx.author.name})")
        await self.bot.reply(ctx, text=f"Added {stream} to stream list.")
    
    @streams.command(name="del")
    async def stream_del(self, ctx, *, num: int):
        """Delete a stream from the stream list"""
        num -= 1
        if ctx.author.name not in self.bot.streams[f"{ctx.guild.id}"][num]:
            if not ctx.channel.permissions_for(ctx.author).manage_messages:
                return await self.bot.reply(ctx, text="You didn't add that stream", delete_after=5, ping=True)
        removed = self.bot.streams[f"{ctx.guild.id}"].pop(num)
        await self.bot.reply(ctx, text=f"<{removed}> removed from streams list.")
    
    @streams.command(name="clear")
    @commands.has_permissions(manage_messages=True)
    async def stream_clear(self, ctx):
        """Remove all streams from guild stream list"""
        self.bot.streams[f"{ctx.guild.id}"] = []
        await self.bot.reply(ctx, text="Streams cleared.")
    
    @commands.command(hidden=True)
    async def gherkin(self, ctx):
        """DON'T LET ME GOOOOOO AGAIN"""
        await self.bot.reply(ctx, text="https://www.youtube.com/watch?v=L4f9Y-KSKJ8")
    
    @commands.command(hidden=True)
    @commands.is_owner()
    async def metro(self, ctx):
        """GET. OFF. THE METRO. NOOOOOOOOOOW."""
        await self.bot.reply(ctx, file=discord.File('Get off the metro now.mp3'))
    
    @commands.command()
    async def mbemba(self, ctx):
        """Mbemba When..."""
        facts = [
            "Matt Ritchie nailing a fan in the balls with a corner flag after a last minute goal against Everton",
            "Director of Football Dennis Wise vetoing a cut-price deal for Bastian Schweinsteiger in favour of "
            "loaning "
            "a player he'd seen on YouTube",
            "German international Dietmar Hamann, in his first season at the club, receiving the secret Santa gift of "
            "a copy of Mein Kampf",
            "Alessandro Pistone receiving the secret Santa gift of a sheep's heart because he \"didn't have one of "
            "his "
            "own\"",
            "Alan Shearer punching, and subsequently knocking out, Keith Gillespie on a club trip to Dublin because "
            "Gillespie dropped some cutlery",
            "Alan Pardew blaming a 2-0 defeat away at Chelsea in August 2012 on the Notting Hill Carnival",
            "Alan Pardew blaming a lack of signings in the summer of 2012 on the idea that too many potential players "
            "were busy watching the Olympics",
            "Ruud Gullit dropping both Alan Shearer and Duncan Ferguson for the Tyne-Wear Derby in favour of "
            "Sunderland supporting Paul Robinson",
            "Joe Kinnear ringing up TalkSport to declare himself Newcastle's new Director of Football and calling our "
            "best player \"Yohan Kebab\"",
            "Kevin Keegan convincing Rob Lee to join Newcastle by telling him it was closer to London than "
            "Middlesbrough is",
            "Shola Ameobi being asked what his teammates call him and replying \"Shola\" then being asked what Sir "
            "Bobby calls him and saying \"Carl Cort\"",
            "Kieron Dyer and Lee Bowyer both being sent off against Aston Villa for fighting each other",
            "Kenny Dalglish selling Les Ferdinand and David Ginola, and replacing them with 35 year old Ian Rush and "
            "33 year old John Barnes",
            "John Barnes being our top scorer with six goals.",
            "Allowing Lomana LuaLua to play against us while he was on loan at Portsmouth. Then him scoring. Then him "
            "doing somersaults in celebration",
            "that fan punching a police horse",
            "Nobby Solano withholding his number, ringing up Sir Bobby Robson, and playing his trumpet down the phone "
            "to him",
            "Spending nearly £6m on Spanish defender Marcelino and him only making 17 appearances over 4 years "
            "because "
            "of a broken finger",
            "David Ginola being told he couldn't smoke on the team bus because it was unhealthy, just as the bus "
            "pulled up to buy the squad fish & chips",
            "Daryl Janmaat breaking two fingers by punching a wall because he was angry about being substituted after "
            "injuring his groin",
            "Andy Carroll receiving a court order that forced him to live with Kevin Nolan",
            "Joe Kinnear going on a scouting trip to Birmingham and coming away impressed by Shane Ferguson, "
            "who was on loan there from Newcastle",
            "Alan Pardew headbutting David Meyler in the middle of a match against Hull",
            "Lee Clark, then a Sunderland player, turning up at the 1998 FA Cup final between Arsenal and Newcastle "
            "in "
            "a \"Sad Mackem BasChampionships\" t-shirt",
            "Clarence Acuna getting pulled over by the police while drunk and dressed as Captain Hook, citing he was "
            "too embarrassed to walk in fancy dress",
            "Faustino Asprilla agreeing to join Newcastle because he was told it was by the sea and assuming it would "
            "be full of beaches and bikinis",
            "Faustino Asprilla turning up to training 40 mins early rather than his usual 20 mins late because he "
            "didn't know the clocks had changed",
            "Alan Pardew being given an eight year contract, which still has another three years to run on it - two "
            "years after he left",
            "Kevin Keegan threatening to drop his entire back four of Watson, Peacock, Howey and Beresford after they "
            "said they wanted to play safer",
            "Freddy Shepherd and Douglas Hall being caught calling all female Newcastle supporters \"dogs\"",
            "Yohan Cabaye being denied a visa for a preseason tour of America due to an unpaid dentist bill",
            "Steve McClaren requesting players attend home games in suits so Chancel Mbemba and Florian Thauvin "
            "arrived in tuxedos",
            "When Steven Taylor was shot by a sniper: https://www.youtube.com/watch?v=vl3HnU0HOhk",
            "Selling Andy Carroll for a club record £35m and replacing him days later with 33 year old Shefki Kuqi on "
            "a free transfer",
            "Adjusting our ticketing structure after the fans chanted \"If Sammy Ameobi scores we're on the pitch\". "
            "He scored. They went on the pitch",
            "Sammy Ameobi and Demba Ba threatening a noise complaint to a hotel before realising that someone had "
            "left "
            "a radio on in their wardrobe",
            "Having a kick-off against Leicester delayed for an hour because our newly installed electronic screen "
            "nearly blew off in the wind",
            "Shola Ameobi ringing the police because of a suspected break in, then cancelling the call out when he "
            "realised his house was just untidy",
            "Patrick Kluivert losing a $4,000 diamond earring in a UEFA Cup match, which was more than our opponents' "
            "best paid player earned a week",
            "At closing time, Faustino Asprilla would often invite entire nightclubs of people back to his house to "
            "carry on partying",
            "Charles N'Zogbia being forced to hand in a transfer request after Joe Kinnear called him \"Charles "
            "Insomnia\" in a post-match interview",
            "Steven Taylor having to have his jaw wired because Andy Carroll punched him and broke it *at the "
            "training "
            "ground*",
            "NUFC being forced to deny that we were subject to a takeover attempt by WWE owner Vince McMahon",
            "when Laurent Robert decided to do this to Olivier Bernard for reasons unknown. "
            "https://www.youtube.com/watch?v=LltnTI7MzIM",
            "Shay Given being awarded man of the match after we lost 5-1 to Liverpool",
            "Laurent Robert throwing literally all his clothing except his Y-fronts into the crowd In his last match",
            "Shola Ameobi appearing on MTV Cribs, and spending most of his time talking about his coffee table",
            "Temuri Ketsbaia scoring against Bolton and throwing his shirt into the crowd, it not being returned so "
            "kicking the hoardings until it was",
            "Shay Given being the only Irishman who didn't know where Dublin is "
            "https://www.youtube.com/watch?v=3Y0kpT_DD6I",
            "John Carver claiming he was the best coach in the Premier League, after winning 9 points from a possible "
            "48",
            "FIFA refusing to allow Hatem Ben Arfa to move to Nice because he'd made one appearance for Newcastle's "
            "reserve side",
            "Barcelona allegedly wanting to sign Steven Taylor, and offering Carles Puyol in exchange",
            "Chancel Mbemba taking to the pitch in the Tyne-Wear derby with \"MBMEMBA\" on the back of his shirt",
            "Newcastle turning down the chance to sign Zinedine Zidane for £1.2m in 1996 by saying he \"wasn't even "
            "good enough to play in Division One\"",
            "Blackburn attempting to get 25 year old Alan Shearer to turn down a move to Newcastle by offering him "
            "the "
            "role of player-manager",
            "Kieron Dyer being injured for a month after poking himself in the eye with a pole during training",
            "Andy Carroll being injured for a month after falling off a bar stool",
            "Uruguayans tweeting abuse such as \"Your mother in a thong\" to Paul Dummett after a tackle on Luis "
            "Suarez may have kept him out the World Cup",
            "Joe Kinnear's first official press conference as Newcastle manager beginning with, \"Which one is Simon "
            "Bird? You're a cunt.\"",
            "Winning the Intertoto Cup, only to discover it's less of a cup and more of a certificate "
            "https://www.shelfsidespurs.com/forum/attachments/toto_plaque2_348x470-jpg.2437/",
            "Then assistant manager John Carver going over to the fans after defeat at Southampton and offering to "
            "fight them",
            "Jonathan Woodgate smashing a pint glass over his own head while on holiday in Ibiza",
            "Duncan Ferguson trying to buy Nolberto Solano a live llama as a Christmas present, but not finding "
            "anybody that would ship one to Newcastle",
            "Losing the Charity Shield 4-0 against Manchester United, putting out the exact same starting XI for the "
            "league fixture and winning 5-0"
        ]
        this = random.choice(facts)
        await self.bot.reply(ctx, text=f"<:mbemba:332196308825931777> Mbemba {this}?")
    
    @commands.command()
    async def radio(self, ctx):
        """Sends a link to the NUFC radio channel"""
        await self.bot.reply(ctx, text="NUFC Radio Coverage: https://www.nufc.co.uk/liveaudio.html")


def setup(bot):
    """Load the NUFC Cog into the bot"""
    bot.add_cog(NUFC(bot))
