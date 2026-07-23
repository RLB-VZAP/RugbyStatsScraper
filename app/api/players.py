import json
import logging
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.player import Player

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


@router.get("", response_model=list[Player])
def list_players() -> list[Player]:
    return load_players()
