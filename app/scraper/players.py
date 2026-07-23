"""Scrapes a URC player page: the banner plus the season stats panels.

The page at `/clubs/{club}/{player}` is a React shell - fetching it yields
~5KB with an empty `<div id="root">`, no `<main>` and no `font-urcHand`. The
three main divs, their columns and the stat panels only exist after the SPA
renders, so there is nothing for BeautifulSoup to walk. What the SPA renders
*from* is the same GraphQL endpoint the roster scraper uses, and the queries
in `app/scraper/queries.py` are the site's own. Reproducing the page means
issuing those queries, not parsing HTML.

The page's three divs map onto this module as:

  1. nav       - the player dropdown is a club's squad (`fetch_squad`), the
                 date dropdown is `fetch_seasons`.
  2. banner    - `PlayerInfo`, from `queries.PLAYER_SQUAD`.
  3. stats     - `PlayerStats`, from `queries.PLAYER_SEASON_STATS`.

(The fourth sibling is a separator and holds nothing.)
"""

import logging
from datetime import date
from typing import Any

from app.core.config import Settings, get_settings
from app.scraper import queries
from app.scraper.client import GraphQLClient, ScraperError
from app.scraper.models import (
    AttackStats,
    DefenceStats,
    DisciplineStats,
    KickingStats,
    LineoutStats,
    PlayerInfo,
    PlayerStats,
    ScrapedClub,
    ScrapedPlayerProfile,
    Season,
)
from app.scraper.slugs import player_slug
from app.scraper.urc import URCScraper

logger = logging.getLogger(__name__)


def _int(value: Any) -> int:
    """A stat the player never recorded comes back null; the page shows 0."""
    return int(value or 0)


def _pct(value: Any) -> float:
    return float(value or 0)


def _as_list(value: Any) -> list[str]:
    """Normalise a source field that is typed String but may hold a list.

    `availableSeasons` and `excludeFromFilter` share a declared type but not a
    shape - the first arrives as a JSON array, the second as a bare string.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _format_birthday(raw: str | None) -> str | None:
    """`1998-04-19` -> `19-04-1998`, the format the banner prints."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10]).strftime("%d-%m-%Y")
    except ValueError:
        logger.warning("Unparseable date of birth %r", raw)
        return None


def _format_height(raw: str | None) -> str | None:
    """`6'2` -> `6'2"`. The source omits the inches mark, the banner shows it."""
    if not raw:
        return None
    height = raw.strip()
    if not height:
        return None
    return height if height.endswith('"') else f'{height}"'


def _format_weight(raw: str | None) -> str | None:
    """`98` -> `98 KG`. The source sends a bare number, the banner adds units."""
    if raw is None:
        return None
    weight = str(raw).strip()
    if not weight:
        return None
    return weight if weight.upper().endswith("KG") else f"{weight} KG"


class PlayerScraper:
    """Fetches the banner and stats behind a club's player pages."""

    def __init__(
        self, client: GraphQLClient, settings: Settings | None = None
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()

    async def fetch_seasons(self, include_hidden: bool = False) -> list[Season]:
        """The player page's season dropdown, newest first.

        By default this mirrors what the dropdown actually offers: the site
        drops the seasons named by `excludeFromFilter` (a season that is
        configured but not yet playable). Pass `include_hidden=True` for the
        raw list.
        """
        data = await self._client.execute(queries.SEASONS)
        config = data.get("seasonsConfiguration") or {}
        hidden = set() if include_hidden else set(_as_list(config.get("excludeFromFilter")))

        seasons = [
            Season(key=str(entry["key"]), label=str(entry.get("label") or entry["key"]))
            for entry in config.get("seasons") or []
            if entry.get("key") is not None and str(entry["key"]) not in hidden
        ]
        if not seasons:
            raise ScraperError("No seasons returned by the source API")
        return seasons

    async def default_season_id(self) -> str:
        """The season the player page opens on when nothing is selected."""
        data = await self._client.execute(queries.SEASONS)
        config = data.get("seasonsConfiguration") or {}
        default = config.get("defaultSeasonExceptRound") or config.get(
            "defaultSeasonForRound"
        )
        if not default:
            raise ScraperError("Source API did not name a default season")
        return str(default)

    def _to_info(self, raw: dict[str, Any]) -> PlayerInfo | None:
        first_name = (raw.get("playerFirstName") or "").strip()
        last_name = (raw.get("playerLastName") or "").strip()
        if not first_name and not last_name:
            return None

        return PlayerInfo(
            name=first_name,
            surname=last_name,
            age=raw.get("playerAge"),
            birthday=_format_birthday(raw.get("dateOfBirth")),
            height=_format_height(raw.get("playerHeight")),
            weight=_format_weight(raw.get("playerWeight")),
            birth_country=raw.get("birthcountry"),
            national_team=raw.get("nationalTeam"),
            # The `font-urcHand` element in the banner's third column.
            position=raw.get("playerPosition"),
            image_url=raw.get("headshots"),
        )

    async def fetch_squad(self, club_source_id: int) -> dict[int, dict[str, Any]]:
        """Every banner in one club's squad, keyed by player id.

        The banner query has no per-player form, so a single player still
        costs a squad. Callers scraping several players of one club should
        call this once.
        """
        data = await self._client.execute(
            queries.PLAYER_SQUAD, {"currentClub": [str(club_source_id)]}
        )
        squads = (data.get("playerThemeSettings") or {}).get("squads") or []

        members: dict[int, dict[str, Any]] = {}
        for squad in squads:
            for raw in squad.get("squad") or []:
                player_id = raw.get("playerId")
                if player_id is None:
                    continue
                # Drop unusable members here rather than after the stats
                # request, so their ids never go into it.
                if not (raw.get("playerFirstName") or "").strip() and not (
                    raw.get("playerLastName") or ""
                ).strip():
                    logger.warning(
                        "Skipping squad member %s (club %s) with no name",
                        player_id,
                        club_source_id,
                    )
                    continue
                members[int(player_id)] = raw

        if not members:
            logger.warning("Club %s returned an empty squad", club_source_id)
        return members

    def _to_stats(self, raw: dict[str, Any]) -> PlayerStats:
        attack = raw.get("attack") or {}
        defence = raw.get("defence") or {}
        discipline = raw.get("discipline") or {}
        kicking = raw.get("kicking") or {}
        lineout = raw.get("lineout") or {}
        scoring = raw.get("scoring") or {}

        return PlayerStats(
            attack=AttackStats(
                # The Attack panel's scoring rows come from `scoring`, not
                # `attack` - the source splits them, the page doesn't.
                points_scored=_int(scoring.get("points")),
                tries_scored=_int(scoring.get("tryScored")),
                assists=_int(attack.get("tryAssist")),
                clean_breaks=_int(attack.get("cleanBreak")),
                defenders_beaten=_int(attack.get("defenderBeaten")),
                carries=_int(attack.get("carries")),
                metres_gained=_int(attack.get("metresMade")),
                offloads=_int(attack.get("offload")),
            ),
            defence=DefenceStats(
                number_of_tackles=_int(defence.get("tackle")),
                missed_tackles=_int(defence.get("missedTackle")),
                tackle_success_pct=_pct(defence.get("percentTackleMade")),
                turnovers_won=_int(defence.get("turnoverWon")),
                # "Turnovers Lost" sits in the Defence panel but is an attack
                # stat upstream.
                turnovers_lost=_int(attack.get("errors")),
            ),
            kicking=KickingStats(
                penalties_scored=_int(scoring.get("penaltyGoal")),
                conversions_scored=_int(scoring.get("conversion")),
                drop_goals=_int(scoring.get("dropGoal")),
                kicks_from_hand=_int(kicking.get("kicksInPlay")),
                kick_success_pct=_pct(scoring.get("percentGoals")),
            ),
            discipline=DisciplineStats(
                yellow_cards=_int(discipline.get("yellowCard")),
                red_cards=_int(discipline.get("redCard")),
                penalties_conceded=_int(discipline.get("penaltyConceded")),
                scrum_offences=_int(discipline.get("scrumOffence")),
                lineout_offences=_int(discipline.get("lineoutOffence")),
            ),
            lineouts=LineoutStats(
                lineouts_won=_int(lineout.get("lineoutThrowsWon")),
                lineouts_lost=_int(lineout.get("lineoutThrowsLost")),
                lineout_success_pct=_pct(lineout.get("percentLineoutsWon")),
                lineouts_steals=_int(lineout.get("lineoutSteals")),
            ),
        )

    async def fetch_stats(
        self, player_ids: list[int], season_id: str
    ) -> dict[int, dict[str, Any]]:
        """One season's stats row per player, keyed by player id.

        `player_id` takes a list, so a whole squad is one request. Players
        with no row for the season are simply absent from the result.
        """
        if not player_ids:
            return {}

        data = await self._client.execute(
            queries.PLAYER_SEASON_STATS,
            {"playerId": [int(pid) for pid in player_ids], "seasonId": [int(season_id)]},
        )

        rows: dict[int, dict[str, Any]] = {}
        for row in data.get("playerseasonstats") or []:
            player_id = row.get("player_id")
            if player_id is None:
                continue
            rows[int(player_id)] = row
        return rows

    def _to_profile(
        self,
        club: ScrapedClub,
        member: dict[str, Any],
        row: dict[str, Any] | None,
    ) -> ScrapedPlayerProfile | None:
        info = self._to_info(member)
        if info is None:
            logger.warning(
                "Skipping squad member %s (%s) with no name",
                member.get("playerId"),
                club.slug,
            )
            return None

        # `knownName` is the site's own slug; fall back to rebuilding it only
        # when the banner omits it.
        slug = (member.get("knownName") or "").strip() or player_slug(
            info.name, info.surname
        )
        player_stats = ((row or {}).get("player_stats") or {}).get("playerStats") or {}
        scoring = player_stats.get("scoring") or {}

        return ScrapedPlayerProfile(
            source_id=int(member["playerId"]),
            slug=slug,
            club_source_id=club.source_id,
            club_slug=club.slug,
            stats_url=f"{self._settings.stats_base_url}/clubs/{club.slug}/{slug}",
            season_id=(row or {}).get("season_id"),
            season_name=(row or {}).get("season_name"),
            # The row's own matches_played/minutes_played are 0 for everyone;
            # the populated counters live under `scoring`.
            matches_played=_int(scoring.get("appearances")),
            minutes_played=_int(scoring.get("minutesPlayed")),
            info=info,
            stats=self._to_stats(player_stats),
        )

    async def fetch_club_profiles(
        self, club: ScrapedClub, season_id: str | None = None
    ) -> list[ScrapedPlayerProfile]:
        """Every player page of one club, for one season.

        Two requests per club regardless of squad size. `season_id` defaults
        to the season the site opens on.
        """
        season_id = season_id or await self.default_season_id()

        members = await self.fetch_squad(club.source_id)
        rows = await self.fetch_stats(list(members), season_id)

        profiles = [
            profile
            for player_id, member in members.items()
            if (profile := self._to_profile(club, member, rows.get(player_id)))
            is not None
        ]
        profiles.sort(key=lambda profile: (profile.info.surname, profile.info.name))

        missing = len(profiles) - len(rows)
        if missing > 0:
            logger.info(
                "%s: %s of %s players have no %s stats row",
                club.slug,
                missing,
                len(profiles),
                season_id,
            )
        return profiles

    async def fetch_player(
        self, club: ScrapedClub, player_id: int, season_id: str | None = None
    ) -> ScrapedPlayerProfile:
        """A single player page. Costs the same as the whole club's."""
        season_id = season_id or await self.default_season_id()

        members = await self.fetch_squad(club.source_id)
        member = members.get(int(player_id))
        if member is None:
            raise ScraperError(
                f"Player {player_id} is not in {club.slug}'s squad"
            )

        rows = await self.fetch_stats([int(player_id)], season_id)
        profile = self._to_profile(club, member, rows.get(int(player_id)))
        if profile is None:
            raise ScraperError(f"Player {player_id} has no usable banner data")
        return profile


async def scrape_player_profiles(
    club_slug: str | None = None,
    season_id: str | None = None,
    settings: Settings | None = None,
) -> list[ScrapedPlayerProfile]:
    """Scrape every player page of one club, or of the whole league.

    Manages the HTTP client for a one-off scrape, the way `scrape_rosters`
    does. Omit `club_slug` for all 16 clubs.
    """
    settings = settings or get_settings()
    async with GraphQLClient(settings) as client:
        clubs = await URCScraper(client, settings).fetch_clubs()
        if club_slug is not None:
            clubs = [club for club in clubs if club.slug == club_slug]
            if not clubs:
                raise ScraperError(f"No club with slug {club_slug!r}")

        scraper = PlayerScraper(client, settings)
        season_id = season_id or await scraper.default_season_id()

        profiles: list[ScrapedPlayerProfile] = []
        for club in clubs:
            profiles.extend(await scraper.fetch_club_profiles(club, season_id))
        return profiles
