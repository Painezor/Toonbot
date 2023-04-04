"""World of Warships Game Modes"""
import dataclasses
import typing


@dataclasses.dataclass
class GameMode:
    """ "An Object representing different Game Modes"""

    description: str
    image: str
    name: str
    tag: str

    def __init__(self, data: dict) -> None:
        for k, val in data.items():
            setattr(self, k, val)

    @property
    def emoji(self) -> typing.Optional[str]:
        """Get the Emoji Representation of the game mode."""
        return {
            "BRAWL": "<:Brawl:989921560901058590>",
            "CLAN": "<:Clan:989921285918294027>",
            "COOPERATIVE": "<:Coop:989844738800746516>",
            "EVENT": "<:Event:989921682007420938>",
            "PVE": "<:Scenario:989921800920109077>",
            "PVE_PREMADE": "<:Scenario_Hard:989922089303687230>",
            "PVP": "<:Randoms:988865875824222338>",
            "RANKED": "<:Ranked:989845163989950475>",
        }.get(self.tag, None)
