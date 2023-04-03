"""Information related to Players from the Wows API"""


class Player:
    """A World of Warships player."""

    def __init__(self, account_id: int, **kwargs) -> None:
        # Player Search Endpoint
        self.account_id: int = account_id
        self.nickname: str = kwargs.pop("nickname", None)

        # Player Personal Data Endpoint.
        self.created_at: datetime.datetime  # Player Account creation
        self.hidden_profile: bool  # Player Stats are hidden?
        self.karma: int  # Player Karma
        self.last_battle_time: datetime.datetime
        self.levelling_points: int  # Player level - Garbage
        self.levelling_tier: int  # Smae.
        self.logout_at: datetime.datetime
        self.stats_updated_at: datetime.datetime

        # CB Season Stats
        self.clan: typing.Optional[Clan] = None

        # Keyed By Season ID.
        self.clan_battle_stats: dict[int, PlayerCBStats] = {}

    async def fetch_stats(self) -> PlayerStats:
        """Fetch Player Stats from API"""
        parmas = {"application_id": WG_ID, "account_id": self.account_id}

        url = API + self.region.domain + "/wows/account/info/"

        extra = ", ".join(f"statistics.{i}" for i in MODE_STRINGS)
        parmas.update({"extra": extra})

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=parmas) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    logger.error("%s on %s -> %s", resp.status, url, err)
                    raise ConnectionError()
            data = await resp.json()

        statistics = PlayerStats(data.pop("statistics"))
        for k, value in data:
            if k == "private":
                continue
            else:
                setattr(self, k, value)
        return statistics

    async def fetch_ship_stats(self, ship: Ship) -> PlayerStats:
        """Get stats for a player in a specific ship"""
        url = API + self.region.domain + "/wows/ships/stats/"
        params = {"application_id": WG_ID, "account_id": self.account_id}
        params.update(
            {"ship_id": ship.ship_id, "extra": ", ".join(MODE_STRINGS)}
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    raise ConnectionError(resp.status)
                data = await resp.json()

        statistics = PlayerStats(data.pop("statistics"))
        return statistics

    @property
    def region(self) -> Region:
        """Get a Region object based on the player's ID number."""
        if 0 < self.account_id < 500000000:
            raise ValueError("CIS Is no longer supported.")
        elif 500000000 < self.account_id < 999999999:
            return Region.EU
        elif 1000000000 < self.account_id < 1999999999:
            return Region.NA
        else:
            return Region.SEA

    @property
    def community_link(self) -> str:
        """Get a link to this player's community page."""
        dom = self.region.domain
        uid = self.account_id
        nom = self.nickname
        return f"https://worldofwarships.{dom}/community/accounts/{uid}-{nom}/"

    @property
    def wows_numbers(self) -> str:
        """Get a link to this player's wows_numbers page."""
        dom = {Region.NA: "na", Region.SEA: "asia", Region.EU: ""}[self.region]
        name = self.nickname
        acc_id = self.account_id
        return f"https://{dom}.wows-numbers.com/player/{acc_id},{name}/"

    async def get_clan_info(self) -> typing.Optional[Clan]:
        """Get a Player's clan"""
        link = API + self.region.domain + "/wows/clans/accountinfo/"
        parms = {
            "application_id": WG_ID,
            "account_id": self.account_id,
            "extra": "clan",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(link, params=parms) as resp:
                if resp.status != 200:
                    logger.error("%s on %s", resp.status, link)
                    return None
                data = await resp.json()

        if (data := data["data"].pop(str(self.account_id))) is None:
            self.clan = None
            return None

        self.joined_clan_at = datetime.datetime.utcfromtimestamp(
            data.pop("joined_at")
        )

        clan_id = data.pop("clan_id")
        clan = Clan(clan_id)
        clan_data = data.pop("clan")
        clan.name = clan_data.pop("name")
        clan.tag = clan_data.pop("tag")

        self.clan = clan
        return self.clan
