"""Maps the scraper's raw shapes onto the `Player` the API serves.

`ScrapedPlayerProfile` is what the source site holds: a name, a position, and
five panels of counting stats. `app.models.player.Player` is what a game
needs: ids, a price, and seven 0-100 abilities. Nothing in the first is
directly the second - the arithmetic in `ratings.py` bridges them, and this
module handles the rest of the record (names, ids, rounding).

    from app.processing import profile_to_player

    player = profile_to_player(profile)
"""

from app.models.player import Player
from app.processing.positions import club_id, normalise_position, position_id
from app.processing.ratings import market_value, rate
from app.scraper.models import ScrapedPlayerProfile


def player_name(profile: ScrapedPlayerProfile) -> str:
    """"Handre" + "Pollard" -> "Handre Pollard".

    The banner always carries at least one of the two - `PlayerScraper` drops
    squad members with neither - so this never comes back empty.
    """
    return " ".join(part for part in (profile.info.name, profile.info.surname) if part)


def profile_to_player(profile: ScrapedPlayerProfile) -> Player:
    """Convert one scraped player page into the API's `Player`.

    Pure and deterministic: same profile in, same player out, no network and
    no clock. `clubId` and `positionId` are derived from the club slug and
    the normalised position name (see `positions.py`) rather than looked up,
    since no clubs or positions tables exist yet.
    """
    position = normalise_position(profile.info.position)
    scores = rate(profile, position)

    return Player(
        club_id=club_id(profile.club_slug),
        position_id=position_id(position),
        player_name=player_name(profile),
        value=market_value(scores, profile.info.age),
        # The model is an int 0-100; the maths runs in floats throughout and
        # only rounds here, so intermediate ratings never lose precision.
        attacking_ability=round(scores["attacking"]),
        defensive_ability=round(scores["defensive"]),
        kicking_ability=round(scores["kicking"]),
        discipline=round(scores["discipline"]),
        consistency=round(scores["consistency"]),
        fitness=round(scores["fitness"]),
        current_form=round(scores["form"]),
    )


def profiles_to_players(profiles: list[ScrapedPlayerProfile]) -> list[Player]:
    """Convert a whole scrape, most valuable player first."""
    players = [profile_to_player(profile) for profile in profiles]
    players.sort(key=lambda player: (-player.value, player.player_name))
    return players
