import json
import logging
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.models.player import Player
from app.processing import profiles_to_players
from app.scraper import ScraperError, scrape_player_profiles

router = APIRouter(prefix="/players", tags=["players"])

logger = logging.getLogger(__name__)

# Served when no exported file exists, so the endpoint is never empty on a
# fresh checkout. Real data comes from `scripts/export_players.py`, which
# scrapes the league and runs it through `app.processing`.
_PLACEHOLDER: list[Player] = [
    Player(
        club_id=UUID("11111111-1111-1111-1111-111111111111"),
        position_id=UUID("22222222-2222-2222-2222-222222222222"),
        player_name="Manie Libbok",
        value=5.5,
        attacking_ability=80,
        defensive_ability=75,
        kicking_ability=70,
        discipline=85,
        consistency=78,
        fitness=90,
        current_form=82,
    )
]


@lru_cache
def load_players() -> list[Player]:
    """The exported players, or the placeholder if nothing's been exported.

    Cached for the life of the process - the file is a scrape snapshot, not
    live data, so re-reading it per request buys nothing. Restart the app (or
    `load_players.cache_clear()`) after re-exporting.
    """
    path = get_settings().players_file
    if not path.exists():
        logger.info("No player export at %s; serving placeholder data", path)
        return _PLACEHOLDER

    raw = json.loads(path.read_text(encoding="utf-8"))
    # The file is written in the API's own camelCase shape, which the model
    # accepts directly via its alias generator.
    return [Player.model_validate(entry) for entry in raw]


def _save_players(players: list[Player]) -> None:
    """Write players to the configured snapshot in the API's camelCase shape.

    Same format `load_players` reads and `scripts/export_players.py` writes, so
    the three stay interchangeable.
    """
    path = get_settings().players_file
    payload = [player.model_dump(by_alias=True, mode="json") for player in players]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def _scrape_players(club: str | None, season: str | None) -> list[Player]:
    profiles = await scrape_player_profiles(club_slug=club, season_id=season)
    return profiles_to_players(profiles)


@router.get("", response_model=list[Player])
async def list_players(
    refresh: bool = Query(
        False,
        description="Scrape the URC live and return fresh players instead of the "
        "saved snapshot. Slow (~30s for the whole league) - scope it with `club` "
        "to speed it up. A full-league refresh also updates the saved snapshot.",
    ),
    club: str | None = Query(
        None,
        description="Club slug (e.g. 'edinburgh') to scrape when refreshing; "
        "default is every club.",
    ),
    season: str | None = Query(
        None,
        description="Season id (e.g. '202401') to scrape when refreshing; "
        "default is the current season.",
    ),
) -> list[Player]:
    if not refresh:
        return load_players()

    try:
        players = await _scrape_players(club, season)
    except ScraperError as exc:
        logger.warning("Live scrape failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"scrape failed: {exc}") from exc

    # Persist only a full-league, current-season scrape - that's the canonical
    # snapshot GET /players serves. A scoped scrape returns fresh but mustn't
    # clobber the full file with a partial one. cache_clear() so the next plain
    # read picks up what we just wrote rather than the stale cached list.
    if club is None and season is None:
        try:
            _save_players(players)
            load_players.cache_clear()
        except OSError as exc:
            # A failed write shouldn't sink the request - we still have the data
            # in hand to return.
            logger.warning(
                "Could not save scrape to %s: %s",
                get_settings().players_file,
                exc,
            )

    return players
