"""Dump URC player pages - banner plus season stats - as JSON.

    python -m scripts.scrape_player_stats                      # whole league
    python -m scripts.scrape_player_stats -c edinburgh         # one club
    python -m scripts.scrape_player_stats -s 202401            # a past season
    python -m scripts.scrape_player_stats --seasons            # season dropdown
    python -m scripts.scrape_player_stats -c leinster -o p.json
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.scraper import (
    GraphQLClient,
    PlayerScraper,
    ScraperError,
    scrape_player_profiles,
)


async def _collect(club: str | None, season: str | None, seasons_only: bool) -> list[dict]:
    if seasons_only:
        async with GraphQLClient() as client:
            return [
                season.model_dump()
                for season in await PlayerScraper(client).fetch_seasons()
            ]

    profiles = await scrape_player_profiles(club_slug=club, season_id=season)
    # by_alias keeps the source's own `*_%` stat names in the JSON.
    return [profile.model_dump(by_alias=True) for profile in profiles]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-c", "--club", help="club slug (e.g. edinburgh); default is every club"
    )
    parser.add_argument(
        "-s", "--season", help="season id (e.g. 202401); default is the current one"
    )
    parser.add_argument(
        "--seasons", action="store_true", help="list the season dropdown and exit"
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="write JSON here instead of stdout"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        payload = asyncio.run(_collect(args.club, args.season, args.seasons))
    except ScraperError as exc:
        print(f"scrape failed: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {len(payload)} entries to {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
