"""Scrape the URC and write the API-shaped players `GET /players` serves.

The scrape gives raw counting stats; `app.processing` converts them into the
rated `Player` shape (see `autoimpl/2026-07-23-player-conversion.md` for how
the ratings are derived). Output is camelCase JSON, ready to be served or
loaded straight into a game.

    python -m scripts.export_players                    # league -> data/players.json
    python -m scripts.export_players -c edinburgh       # one club
    python -m scripts.export_players -s 202401          # a past season
    python -m scripts.export_players -o -               # stdout
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.core.config import get_settings
from app.models.player import Player
from app.processing import profiles_to_players
from app.scraper import ScraperError, scrape_player_profiles


async def _build(club: str | None, season: str | None) -> list[Player]:
    profiles = await scrape_player_profiles(club_slug=club, season_id=season)
    return profiles_to_players(profiles)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-c", "--club", help="club slug (e.g. edinburgh); default is every club"
    )
    parser.add_argument(
        "-s", "--season", help="season id (e.g. 202401); default is the current one"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="where to write; '-' for stdout. Default is the configured "
        "players_file, which is what the API reads.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        players = asyncio.run(_build(args.club, args.season))
    except ScraperError as exc:
        print(f"scrape failed: {exc}", file=sys.stderr)
        return 1

    # by_alias for the camelCase the API exposes; mode="json" so the UUIDs
    # come out as strings rather than UUID objects.
    payload = [player.model_dump(by_alias=True, mode="json") for player in players]
    text = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.output and str(args.output) == "-":
        print(text)
        return 0

    destination = args.output or get_settings().players_file
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    print(f"wrote {len(payload)} players to {destination}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
