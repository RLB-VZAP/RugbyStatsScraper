"""Scrapes the United Rugby Championship club and player rosters.

Two calls cover the whole league: one for the 16 clubs, one for every player.
From that we derive the same URLs the stats site links to from its `club-card`
and `player-card` anchors, which is what the per-player stats scrape will walk.
"""

import logging
from collections import defaultdict
from typing import Any

from app.core.config import Settings, get_settings
from app.scraper import queries
from app.scraper.client import GraphQLClient, ScraperError
from app.scraper.models import ScrapedClub, ScrapedPlayer, ScrapedRoster
from app.scraper.slugs import club_slug, player_slug

logger = logging.getLogger(__name__)


class URCScraper:
    """Fetches clubs and their squads from the URC data API."""

    def __init__(
        self, client: GraphQLClient, settings: Settings | None = None
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()

    def _club_url(self, slug: str) -> str:
        return f"{self._settings.stats_base_url}/clubs/{slug}"

    def _players_url(self, slug: str) -> str:
        return f"{self._settings.stats_base_url}/clubs/{slug}/players"

    def _player_url(self, club: str, player: str) -> str:
        # Player pages hang directly off the club, not off /players - the
        # player-card anchor is `/clubs/{club}/{first}-{last}`.
        return f"{self._settings.stats_base_url}/clubs/{club}/{player}"

    async def fetch_clubs(self) -> list[ScrapedClub]:
        """Every club in the competition, in id order."""
        data = await self._client.execute(queries.CLUBS)

        raw_clubs = data.get("clubs") or []
        theme = (data.get("clubThemeSettings") or {}).get("clubs") or []
        names_by_id = {
            entry["id"]: entry["fullName"]
            for entry in theme
            if entry.get("id") is not None and entry.get("fullName")
        }

        clubs: list[ScrapedClub] = []
        for raw in raw_clubs:
            club_id = raw.get("id")
            if club_id is None:
                continue
            # Prefer the theme-settings name: it's what the site slugs URLs
            # from, and it differs from the API name for several clubs.
            name = names_by_id.get(club_id) or raw.get("team_name")
            if not name:
                logger.warning("Skipping club %s with no usable name", club_id)
                continue
            slug = club_slug(name)
            clubs.append(
                ScrapedClub(
                    source_id=club_id,
                    name=name,
                    slug=slug,
                    url=self._club_url(slug),
                    players_url=self._players_url(slug),
                )
            )

        if not clubs:
            raise ScraperError("No clubs returned by the source API")

        clubs.sort(key=lambda club: club.source_id)
        return clubs

    def _to_player(self, raw: dict[str, Any], club: ScrapedClub) -> ScrapedPlayer | None:
        details = raw.get("player_data") or {}
        first_name = (details.get("firstName") or "").strip()
        last_name = (details.get("lastName") or "").strip()
        if not first_name or not last_name:
            logger.warning(
                "Skipping player %s (%s) with incomplete name", raw.get("id"), club.slug
            )
            return None

        slug = player_slug(first_name, last_name)
        height = details.get("height") or {}
        weight = details.get("weight") or {}
        position = details.get("normalPosition") or {}
        country = details.get("countryOfBirth") or {}

        return ScrapedPlayer(
            source_id=raw["id"],
            club_source_id=club.source_id,
            club_slug=club.slug,
            slug=slug,
            first_name=first_name,
            last_name=last_name,
            known_name=details.get("knownName"),
            position=position.get("name"),
            date_of_birth=details.get("dob"),
            height_m=height.get("heightM"),
            weight_kg=weight.get("weightKg"),
            country_of_birth=country.get("name"),
            birthplace=details.get("birthplace"),
            join_date=details.get("joinDate"),
            leave_date=details.get("leaveDate"),
            stats_url=self._player_url(club.slug, slug),
        )

    async def fetch_players_by_club(
        self, clubs: list[ScrapedClub]
    ) -> dict[int, list[ScrapedPlayer]]:
        """Every player, grouped by club id.

        One request covers the whole league - the API's `teamId` filter is
        accepted but ignored, so we group on each record's `club_id` instead.
        """
        data = await self._client.execute(queries.PLAYERS)
        raw_players = data.get("players") or []

        clubs_by_id = {club.source_id: club for club in clubs}
        grouped: dict[int, list[ScrapedPlayer]] = defaultdict(list)
        unknown_clubs: set[int] = set()

        for raw in raw_players:
            if raw.get("id") is None:
                continue
            club = clubs_by_id.get(raw.get("club_id"))
            if club is None:
                unknown_clubs.add(raw.get("club_id"))
                continue
            player = self._to_player(raw, club)
            if player is not None:
                grouped[club.source_id].append(player)

        if unknown_clubs:
            logger.warning(
                "Dropped players belonging to unlisted clubs: %s", sorted(unknown_clubs)
            )

        for players in grouped.values():
            players.sort(key=lambda player: (player.last_name, player.first_name))

        return dict(grouped)

    async def fetch_rosters(self) -> list[ScrapedRoster]:
        """Every club with its full squad - the entry point for stats scraping."""
        clubs = await self.fetch_clubs()
        players_by_club = await self.fetch_players_by_club(clubs)

        rosters = [
            ScrapedRoster(club=club, players=players_by_club.get(club.source_id, []))
            for club in clubs
        ]
        for roster in rosters:
            if not roster.players:
                logger.warning("Club %s returned no players", roster.club.slug)
        return rosters


async def scrape_rosters(settings: Settings | None = None) -> list[ScrapedRoster]:
    """Convenience wrapper that manages the HTTP client for a one-off scrape."""
    settings = settings or get_settings()
    async with GraphQLClient(settings) as client:
        return await URCScraper(client, settings).fetch_rosters()
