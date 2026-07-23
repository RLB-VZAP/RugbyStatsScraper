"""URL slug derivation, mirroring what the stats site's frontend does.

The stats SPA builds its own links client-side rather than getting them from
the API, so these helpers are deliberate reimplementations of the JavaScript
in the site bundle. Keep them faithful - if they drift, the URLs we hand to
the stats scraper 404.
"""

import re

_WHITESPACE = re.compile(r"\s+")
_CLUB_DISALLOWED = re.compile(r"[^a-z0-9-]")
_TRAILING_HYPHENS = re.compile(r"-+$")

# The player-card link splits on literal "%20" as well as whitespace.
_PLAYER_SEPARATOR = re.compile(r"%20|\s+")


def club_slug(full_name: str) -> str:
    """Slug for a club, from its `clubThemeSettings.fullName`.

    JS equivalent:
        fullUrl.trim().toLowerCase().replace(/\\s+/g, "-")
               .replace(/[^a-z0-9-]/g, "").replace(/-+$/, "")

    Note the site uses `fullName` from `clubThemeSettings` and a hardcoded
    `fullUrl` interchangeably; they currently agree for all 16 clubs (e.g.
    both give "Edinburgh", not the API's "Edinburgh Rugby"), which is why we
    slug the theme-settings name rather than the `clubs` query name.
    """
    slug = _WHITESPACE.sub("-", full_name.strip().lower())
    slug = _CLUB_DISALLOWED.sub("", slug)
    return _TRAILING_HYPHENS.sub("", slug)


def player_slug(first_name: str, last_name: str) -> str:
    """Slug for a player, from their first and last name.

    JS equivalent:
        `${first.toLowerCase().replace(/%20|\\s+/g, "-")}-${last.toLowerCase()
          .replace(/%20|\\s+/g, "-")}`

    Punctuation is intentionally *not* stripped here - the site doesn't strip
    it either, so "O'Brien" stays "o'brien" in the URL.
    """
    first = _PLAYER_SEPARATOR.sub("-", first_name.strip().lower())
    last = _PLAYER_SEPARATOR.sub("-", last_name.strip().lower())
    return f"{first}-{last}"
