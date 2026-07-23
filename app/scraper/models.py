"""Raw shapes returned by the scraper.

These mirror the source site, not the API. Mapping these onto
`app.models.player.Player` (the camelCase shape the API exposes) is a separate
transform step and is not implemented yet.
"""

from pydantic import BaseModel, ConfigDict, Field


class ScrapedClub(BaseModel):
    """A club as listed on the stats site's /clubs page."""

    source_id: int
    name: str
    slug: str
    url: str
    players_url: str


class ScrapedPlayer(BaseModel):
    """A player as listed on a club's /clubs/{slug}/players page.

    `stats_url` is the entry point for the not-yet-implemented per-player
    stats scrape.
    """

    source_id: int
    club_source_id: int
    club_slug: str
    slug: str
    first_name: str
    last_name: str
    known_name: str | None = None
    position: str | None = None
    date_of_birth: str | None = None
    height_m: float | None = None
    weight_kg: int | None = None
    country_of_birth: str | None = None
    birthplace: str | None = None
    join_date: str | None = None
    leave_date: str | None = None
    stats_url: str


class ScrapedRoster(BaseModel):
    """One club plus every player currently attached to it."""

    club: ScrapedClub
    players: list[ScrapedPlayer]


class Season(BaseModel):
    """One entry of the season dropdown in the player page's nav bar.

    `key` is what the stats queries take as `season_id` (e.g. "202501");
    `label` is what the dropdown displays (e.g. "2025/26").
    """

    key: str
    label: str


class _StatBlock(BaseModel):
    """Base for the stat panels.

    Several of the source's stat names end in `%`, which isn't a valid Python
    identifier, so those fields carry an alias. Dump with `by_alias=True` to
    get the source's own key names back.
    """

    model_config = ConfigDict(populate_by_name=True)


class AttackStats(_StatBlock):
    """The player page's "Attack" panel."""

    points_scored: int = 0
    tries_scored: int = 0
    assists: int = 0
    clean_breaks: int = 0
    defenders_beaten: int = 0
    carries: int = 0
    metres_gained: int = 0
    offloads: int = 0


class DefenceStats(_StatBlock):
    """The player page's "Defence" panel."""

    number_of_tackles: int = 0
    missed_tackles: int = 0
    tackle_success_pct: float = Field(default=0.0, alias="tackle_success_%")
    turnovers_won: int = 0
    turnovers_lost: int = 0


class KickingStats(_StatBlock):
    """The player page's "Kicking" panel."""

    penalties_scored: int = 0
    conversions_scored: int = 0
    drop_goals: int = 0
    kicks_from_hand: int = 0
    kick_success_pct: float = Field(default=0.0, alias="kick_success_%")


class DisciplineStats(_StatBlock):
    """The player page's "Discipline" panel."""

    yellow_cards: int = 0
    red_cards: int = 0
    penalties_conceded: int = 0
    scrum_offences: int = 0
    lineout_offences: int = 0


class LineoutStats(_StatBlock):
    """The player page's "Lineouts" panel."""

    lineouts_won: int = 0
    lineouts_lost: int = 0
    lineout_success_pct: float = Field(default=0.0, alias="lineout_success_%")
    lineouts_steals: int = 0


class PlayerStats(BaseModel):
    """Every stat panel on a player page, for one season.

    The source reports a stat the player has never recorded as null rather
    than 0; the scraper collapses those to 0 so a panel is always complete.
    """

    attack: AttackStats = Field(default_factory=AttackStats)
    defence: DefenceStats = Field(default_factory=DefenceStats)
    kicking: KickingStats = Field(default_factory=KickingStats)
    discipline: DisciplineStats = Field(default_factory=DisciplineStats)
    lineouts: LineoutStats = Field(default_factory=LineoutStats)


class PlayerInfo(BaseModel):
    """The player "banner" above the stats - the page's second main div.

    Column one is the biographical text, column two the headshot
    (`image_url`), column three the position (the `font-urcHand` element).
    """

    name: str
    surname: str
    age: int | None = None
    # dd-MM-yyyy, the format the banner prints.
    birthday: str | None = None
    # Feet and inches, as displayed - e.g. `6'2"`.
    height: str | None = None
    # e.g. "98 KG".
    weight: str | None = None
    birth_country: str | None = None
    national_team: str | None = None
    position: str | None = None
    image_url: str | None = None


class ScrapedPlayerProfile(BaseModel):
    """A whole player page: the banner plus one season's stats.

    `season_id` is None when the source held no stats row for the requested
    season - the player exists but never played it. `stats` is then all
    zeroes, which is what the page itself renders.
    """

    source_id: int
    slug: str
    club_source_id: int
    club_slug: str
    stats_url: str
    season_id: str | None = None
    season_name: str | None = None
    matches_played: int = 0
    minutes_played: int = 0
    info: PlayerInfo
    stats: PlayerStats = Field(default_factory=PlayerStats)
