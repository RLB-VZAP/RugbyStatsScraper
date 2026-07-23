"""Dump every URC club and its squad as JSON.

    python -m scripts.scrape_rosters               # full rosters to stdout
    python -m scripts.scrape_rosters --clubs-only  # just the 16 clubs
    python -m scripts.scrape_rosters -o data.json  # write to a file
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.scraper import GraphQLClient, ScraperError, URCScraper


async def _collect(clubs_only: bool) -> list[dict]:
    async with GraphQLClient() as client:
        scraper = URCScraper(client)
        if clubs_only:
            clubs = await scraper.fetch_clubs()
            return [club.model_dump() for club in clubs]
        rosters = await scraper.fetch_rosters()
        return [roster.model_dump() for roster in rosters]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clubs-only", action="store_true", help="only list clubs, skip squads"
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
        payload = asyncio.run(_collect(args.clubs_only))
    except ScraperError as exc:
        print(f"scrape failed: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        total = sum(len(entry.get("players", [])) for entry in payload)
        print(f"wrote {len(payload)} entries ({total} players) to {args.output}",
              file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
