"""Positions, and the per-position benchmarks the ratings are measured against.

A prop and a wing do completely different jobs, so their raw stats are not
comparable: the median wing makes 42 metres per 80 minutes, the median prop
makes 6. Rating both against one league-wide average would make every forward
look terrible. Instead every stat is scored against the median for that
player's own position, so 50 always means "typical for this position".

The numbers in `POSITION_BENCHMARKS` are the real league medians, measured
over the 2025/26 season (897 players, the 610 with at least 160 minutes so a
couple of cameo appearances can't skew a median). Re-derive them by dumping
`scripts/scrape_player_stats.py` and taking per-80 medians per position; they
drift slowly, and being a season or two stale only shifts ratings a point or
two.
"""

from dataclasses import dataclass
from uuid import UUID, uuid5

# Fixed root for every id this package derives. Changing it changes every
# clubId/positionId the API serves, so don't.
NAMESPACE = UUID("6f1c4a2e-1d3b-5f8a-9c47-1e0b2d3a4c5f")

UNKNOWN_POSITION = "unknown"

#: Canonical position names, in shirt-number order.
POSITIONS = (
    "prop",
    "hooker",
    "lock",
    "flanker",
    "number-8",
    "scrum-half",
    "fly-half",
    "centre",
    "wing",
    "fullback",
    UNKNOWN_POSITION,
)

# The source's own values are the lowercase left-hand column ("no. 8" is the
# only surprising one). The rest are here so the mapping survives the site
# renaming things, or a different feed being plugged in.
_ALIASES = {
    "loosehead prop": "prop",
    "tighthead prop": "prop",
    "loose-head prop": "prop",
    "tight-head prop": "prop",
    "front row": "prop",
    "second row": "lock",
    "second-row": "lock",
    "openside flanker": "flanker",
    "blindside flanker": "flanker",
    "back row": "flanker",
    "back-row": "flanker",
    "loose forward": "flanker",
    "no. 8": "number-8",
    "no.8": "number-8",
    "no 8": "number-8",
    "number 8": "number-8",
    "number eight": "number-8",
    "eighthman": "number-8",
    "8": "number-8",
    "scrumhalf": "scrum-half",
    "scrum half": "scrum-half",
    "half-back": "scrum-half",
    "halfback": "scrum-half",
    "flyhalf": "fly-half",
    "fly half": "fly-half",
    "out-half": "fly-half",
    "outhalf": "fly-half",
    "outside-half": "fly-half",
    "stand-off": "fly-half",
    "first five-eighth": "fly-half",
    "center": "centre",
    "inside centre": "centre",
    "outside centre": "centre",
    "midfield": "centre",
    "winger": "wing",
    "left wing": "wing",
    "right wing": "wing",
    "full-back": "fullback",
    "full back": "fullback",
    "utility back": "centre",
    "utility forward": "flanker",
}


def normalise_position(raw: str | None) -> str:
    """Map a source position string onto one of `POSITIONS`.

    Anything unrecognised becomes `"unknown"`, which carries league-average
    benchmarks - two of the 897 players have no position at all.
    """
    if not raw:
        return UNKNOWN_POSITION
    name = " ".join(raw.strip().lower().split())
    if name in POSITIONS:
        return name
    return _ALIASES.get(name, UNKNOWN_POSITION)


def position_id(position: str) -> UUID:
    """A stable UUID for a canonical position name.

    Derived rather than looked up, so the API can name a position id without
    a positions table existing yet. Same name in, same UUID out, forever.
    """
    return uuid5(NAMESPACE, f"position:{normalise_position(position)}")


def club_id(club_slug: str) -> UUID:
    """A stable UUID for a club, from the slug its stats pages live under."""
    return uuid5(NAMESPACE, f"club:{club_slug.strip().lower()}")


@dataclass(frozen=True)
class Benchmarks:
    """League-median per-80 output for one position - the "50 rating" line.

    A player matching every figure here scores 50 across the board. Zero
    medians (a prop's clean breaks, a lock's kicks) are floored to a small
    positive number: they're divisors, and a rare event should score well
    rather than divide by zero.
    """

    carries: float
    metres: float
    defenders_beaten: float
    clean_breaks: float
    offloads: float
    scoring: float  # tries + assists
    tackles: float
    turnovers_won: float
    missed_tackles: float
    kicks_from_hand: float
    penalties_conceded: float


@dataclass(frozen=True)
class Baselines:
    """What an unrated player of this position is assumed to be worth.

    Used for the 134 players with no minutes at all, and blended in for
    anyone short of a full season (see `ratings.shrink`). These are judgement
    calls about the role, not measurements: a fly-half who has never played
    is still assumed to be able to kick.
    """

    attacking: float
    defensive: float
    kicking: float
    discipline: float
    consistency: float
    fitness: float


# Real 2025/26 per-80 medians. See the module docstring.
POSITION_BENCHMARKS: dict[str, Benchmarks] = {
    "prop": Benchmarks(6.4, 5.7, 0.4, 0.1, 0.15, 0.1, 11.4, 0.2, 1.2, 0.5, 1.4),
    "hooker": Benchmarks(8.9, 16.4, 0.8, 0.3, 0.2, 0.3, 13.7, 0.4, 1.3, 0.5, 0.6),
    "lock": Benchmarks(6.6, 9.0, 0.5, 0.1, 0.2, 0.1, 12.1, 0.3, 1.0, 0.5, 0.7),
    "flanker": Benchmarks(9.4, 23.7, 1.5, 0.3, 0.4, 0.2, 13.7, 0.5, 1.4, 0.5, 0.7),
    "number-8": Benchmarks(11.7, 31.1, 1.8, 0.3, 0.4, 0.3, 11.6, 0.3, 1.3, 0.5, 0.6),
    "scrum-half": Benchmarks(5.7, 21.5, 1.0, 0.6, 0.4, 0.7, 6.3, 0.2, 1.9, 10.3, 0.3),
    "fly-half": Benchmarks(7.6, 28.7, 1.4, 0.4, 0.6, 0.4, 6.5, 0.3, 1.8, 5.7, 0.4),
    "centre": Benchmarks(8.2, 29.0, 1.7, 0.7, 0.5, 0.3, 7.3, 0.4, 1.6, 0.7, 0.4),
    "wing": Benchmarks(7.6, 42.4, 2.1, 1.1, 0.6, 0.5, 4.3, 0.4, 1.4, 0.8, 0.4),
    "fullback": Benchmarks(8.6, 38.6, 1.7, 0.7, 0.5, 0.3, 3.1, 0.2, 1.5, 2.2, 0.4),
    # Mid-table across the board, for the handful of players the source gives
    # no position for.
    UNKNOWN_POSITION: Benchmarks(
        8.0, 24.0, 1.3, 0.4, 0.4, 0.3, 9.0, 0.3, 1.4, 1.5, 0.6
    ),
}

POSITION_BASELINES: dict[str, Baselines] = {
    "prop": Baselines(40, 58, 20, 62, 48, 50),
    "hooker": Baselines(45, 58, 22, 66, 48, 52),
    "lock": Baselines(42, 58, 20, 66, 48, 52),
    "flanker": Baselines(48, 60, 22, 64, 48, 54),
    "number-8": Baselines(52, 58, 24, 66, 48, 54),
    "scrum-half": Baselines(52, 46, 60, 72, 48, 58),
    "fly-half": Baselines(55, 44, 72, 72, 48, 55),
    "centre": Baselines(55, 50, 42, 70, 48, 55),
    "wing": Baselines(58, 44, 42, 72, 48, 57),
    "fullback": Baselines(57, 45, 55, 72, 48, 56),
    UNKNOWN_POSITION: Baselines(50, 50, 35, 70, 48, 52),
}


def benchmarks_for(position: str) -> Benchmarks:
    return POSITION_BENCHMARKS[normalise_position(position)]


def baselines_for(position: str) -> Baselines:
    return POSITION_BASELINES[normalise_position(position)]
