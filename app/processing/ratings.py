"""Turns a season's counting stats into the API's 0-100 ability ratings.

The source counts things: 102 carries, 73 tackles, 21 errors. The game wants
judgements: `attackingAbility: 80`. Four steps get from one to the other.

1. **Per 80 minutes.** 102 carries means nothing until you know whether it
   took 200 minutes or 1200. Every counting stat becomes a per-80 rate, so a
   bench player and an ever-present are on the same scale.
2. **Score against the player's own position** (`positions.POSITION_BENCHMARKS`).
   `scale()` maps a rate onto 0-100 with 50 at the positional median, so a
   prop's 6 metres per 80 and a wing's 42 both come out as "average".
3. **Combine** the component scores into one ability with fixed weights.
4. **Shrink towards the positional baseline** by how much the player has
   actually played (`shrink()`). One good half shouldn't produce a 95 rating,
   and the 134 players with no minutes at all still need plausible numbers.

Precision is deliberately not the goal - these feed a game, and the ratings
only have to rank players sensibly and spread out across the range. Every
constant below is a tuning knob; changing one changes the feel of the game,
not the correctness of anything.
"""

from dataclasses import dataclass

from app.processing.positions import Benchmarks, baselines_for, benchmarks_for
from app.scraper.models import ScrapedPlayerProfile

#: Steepness of `scale()`. 1.0 is gentle and clusters everyone near 50; 2.0
#: puts the positional median on 50, a p90 season on ~76 and a p10 on ~20,
#: which is about the spread a squad-building game wants.
STEEPNESS = 2.0

#: Minutes at which a player's own stats and the positional baseline count
#: equally (see `shrink`). 240 = three full matches.
CONFIDENCE_MINUTES = 240.0

#: A full season of rugby, for the "how much did they play" scores. The
#: busiest URC player managed ~1580 minutes; 1000 is a strong regular.
FULL_SEASON_MINUTES = 1000.0


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def scale(rate: float, benchmark: float) -> float:
    """Score a per-80 rate against a positional median. 50 = median.

    Saturating rather than linear, so a freak outlier (one player, three
    tries in twenty minutes) approaches 100 instead of blowing past it, and
    no cap has to be hand-picked per stat.
    """
    if rate <= 0:
        return 0.0
    ratio = (rate / max(benchmark, 0.05)) ** STEEPNESS
    return 100.0 * ratio / (ratio + 1.0)


def band(value: float, low: float, high: float) -> float:
    """Map an already-meaningful number (a percentage, an age) onto 0-100."""
    if high <= low:
        return 0.0
    return clamp((value - low) / (high - low) * 100.0)


def shrink(score: float, baseline: float, minutes: float) -> float:
    """Blend a measured score towards the positional baseline.

    Weight is `minutes / (minutes + CONFIDENCE_MINUTES)`: 0 minutes gives the
    baseline outright, three matches splits it evenly, a full season leaves
    the baseline barely visible. This is the one place small sample sizes are
    handled - every rating goes through it, so none of the others need to
    special-case the player who played eight minutes in September.
    """
    weight = minutes / (minutes + CONFIDENCE_MINUTES) if minutes > 0 else 0.0
    return score * weight + baseline * (1.0 - weight)


def _mix(*parts: tuple[float, float]) -> float:
    """Weighted mean of (score, weight) pairs."""
    total = sum(weight for _, weight in parts)
    return sum(score * weight for score, weight in parts) / total if total else 0.0


def spread(source_id: int, width: int, salt: int = 1) -> int:
    """A small, stable per-player offset in `[-width, +width]`.

    Where a rating can't be measured, every player of a position would
    otherwise land on exactly the same baseline - 164 props all rated 20 for
    kicking reads as a bug, not a judgement. This scatters them a little.
    Derived from the source id rather than randomised, so re-running the
    scraper doesn't reshuffle everyone's ratings; `salt` keeps two uses of it
    on the same player from moving in lockstep.
    """
    return (source_id // salt) % (2 * width + 1) - width


@dataclass(frozen=True)
class Per80:
    """One season's counting stats, expressed per 80 minutes played.

    Zero minutes gives every rate 0; that player is carried by the baseline,
    not by these.
    """

    carries: float
    metres: float
    defenders_beaten: float
    clean_breaks: float
    offloads: float
    scoring: float
    tackles: float
    turnovers_won: float
    missed_tackles: float
    errors: float
    kicks_from_hand: float
    penalties_conceded: float
    cards: float
    set_piece_offences: float

    @classmethod
    def from_profile(cls, profile: ScrapedPlayerProfile) -> "Per80":
        minutes = profile.minutes_played
        per = (lambda total: total / minutes * 80.0) if minutes > 0 else (lambda _: 0.0)

        attack = profile.stats.attack
        defence = profile.stats.defence
        discipline = profile.stats.discipline

        return cls(
            carries=per(attack.carries),
            metres=per(attack.metres_gained),
            defenders_beaten=per(attack.defenders_beaten),
            clean_breaks=per(attack.clean_breaks),
            offloads=per(attack.offloads),
            # Tries and assists are both "you finished the move"; separately
            # they're too rare (a median of 0.2 per 80) to rate on.
            scoring=per(attack.tries_scored + attack.assists),
            tackles=per(defence.number_of_tackles),
            turnovers_won=per(defence.turnovers_won),
            missed_tackles=per(defence.missed_tackles),
            errors=per(defence.turnovers_lost),
            kicks_from_hand=per(profile.stats.kicking.kicks_from_hand),
            penalties_conceded=per(discipline.penalties_conceded),
            # A red is worth about three yellows in how much it hurts a team.
            cards=per(discipline.yellow_cards + 3 * discipline.red_cards),
            set_piece_offences=per(
                discipline.scrum_offences + discipline.lineout_offences
            ),
        )


def attacking_ability(rates: Per80, marks: Benchmarks) -> float:
    """Ball carrying, line breaking and finishing, against positional medians.

    Metres and scoring carry the most weight because they're the outputs;
    carries and offloads are volume, which a forward racks up without
    necessarily threatening anything.
    """
    return _mix(
        (scale(rates.metres, marks.metres), 0.25),
        (scale(rates.scoring, marks.scoring), 0.20),
        (scale(rates.defenders_beaten, marks.defenders_beaten), 0.15),
        (scale(rates.clean_breaks, marks.clean_breaks), 0.15),
        (scale(rates.carries, marks.carries), 0.15),
        (scale(rates.offloads, marks.offloads), 0.10),
    )


def defensive_ability(
    rates: Per80, marks: Benchmarks, tackle_success: float
) -> float:
    """Tackle volume, tackle accuracy and turnovers won.

    `tackle_success` is 0 for the ~150 players the source has no percentage
    for; that means "unknown", not "misses every tackle", so it's dropped
    from the mix rather than scored as zero.
    """
    parts = [
        (scale(rates.tackles, marks.tackles), 0.45),
        (scale(rates.turnovers_won, marks.turnovers_won), 0.20),
    ]
    if tackle_success > 0:
        # Nobody survives below ~50%, and 100% means a light workload, so the
        # band is deliberately narrow: the league median 80% lands on ~61.
        parts.append((band(tackle_success, 50.0, 100.0), 0.35))
    return _mix(*parts)


def kicking_ability(
    rates: Per80, marks: Benchmarks, profile: ScrapedPlayerProfile
) -> float | None:
    """Kicking out of hand, plus goal-kicking for the 63 players who take them.

    Returns None when the player has neither kicked out of hand nor at goal -
    most of the pack, most seasons. That is no evidence of a bad kicker, only
    of a forward nobody hands the ball to, so `rate()` falls back to the
    positional baseline instead of scoring them zero.

    Goal-kicking is nearly all-or-nothing - one or two players per squad take
    every shot - so a 0% success rate almost always means "never asked", not
    "always misses". Players with no attempts are scored on their kicking out
    of hand alone.
    """
    kicking = profile.stats.kicking
    goals = kicking.penalties_scored + kicking.conversions_scored + kicking.drop_goals

    if rates.kicks_from_hand <= 0 and goals <= 0:
        return None

    hand = scale(rates.kicks_from_hand, marks.kicks_from_hand)
    if goals <= 0:
        return hand

    return _mix(
        (hand, 0.40),
        (band(kicking.kick_success_pct, 40.0, 95.0), 0.40),
        # Volume matters too: the team's designated kicker is a better kicker
        # than someone who slotted one conversion in a dead rubber.
        (scale(goals / max(profile.matches_played, 1), 2.0), 0.20),
    )


def discipline_rating(rates: Per80, marks: Benchmarks) -> float:
    """Starts at 100, and every offence takes some off.

    Penalties are scored against the positional median because props concede
    three times as many as wings for reasons that have nothing to do with
    their discipline. Cards and set-piece offences are rare enough to score
    against flat references.
    """
    against_position = rates.penalties_conceded / max(marks.penalties_conceded, 0.05)
    penalties = 35.0 * min(against_position, 2.0)
    # 0.15 per 80 is roughly a yellow card every nine matches.
    cards = min(25.0, 25.0 * rates.cards / 0.15)
    offences = min(10.0, 10.0 * rates.set_piece_offences / 0.30)
    return clamp(100.0 - penalties - cards - offences)


def consistency_rating(
    rates: Per80, marks: Benchmarks, profile: ScrapedPlayerProfile
) -> float:
    """How dependable the player is: do they play, do they finish, do they err.

    With only season totals there's no way to measure match-to-match
    variance, so this is a reliability proxy: selection (a coach picking you
    every week is a consistency judgement), minutes per appearance (starters
    finish games, fringe players get 15 minutes), and error rate.
    """
    minutes_per_game = profile.minutes_played / max(profile.matches_played, 1)
    errors = rates.errors + rates.missed_tackles
    error_benchmark = marks.missed_tackles + 1.5

    return _mix(
        (band(profile.minutes_played, 0.0, FULL_SEASON_MINUTES), 0.40),
        (band(minutes_per_game, 20.0, 75.0), 0.30),
        # Inverted: fewer errors than the positional norm scores above 50.
        (100.0 - scale(errors, error_benchmark), 0.30),
    )


def _age_score(age: int | None) -> float:
    """Physical peak is mid-to-late twenties; both ends of the curve drop off."""
    if age is None:
        return 70.0
    if age < 24:
        return clamp(92.0 - 3.0 * (24 - age), low=62.0)
    if age <= 28:
        return 92.0
    return clamp(92.0 - 3.5 * (age - 28), low=45.0)


def fitness_rating(profile: ScrapedPlayerProfile) -> float:
    """Can they last 80 minutes, week after week, at their age.

    Minutes per appearance is the stamina signal - being left on for the full
    80 is a coach's verdict on your conditioning - and total minutes is the
    durability one: injuries show up as missing minutes.
    """
    minutes_per_game = profile.minutes_played / max(profile.matches_played, 1)
    return _mix(
        (band(minutes_per_game, 25.0, 80.0), 0.40),
        (band(profile.minutes_played, 0.0, FULL_SEASON_MINUTES), 0.25),
        (_age_score(profile.info.age), 0.35),
    )


def form_rating(
    profile: ScrapedPlayerProfile, attacking: float, defensive: float
) -> float:
    """Recent form - a stand-in, because the season totals contain no "recent".

    Real form needs per-match stats (`matchstats` on the same GraphQL
    endpoint, still unscraped). Until then this is season-long production
    weighted by how involved the player currently is, nudged by a small
    per-player offset so a squad doesn't read as ten players on exactly the
    same number. The offset is derived from the player's source id, so it is
    stable across runs rather than random.
    """
    involvement = band(profile.minutes_played, 0.0, FULL_SEASON_MINUTES)
    base = _mix(((attacking + defensive) / 2.0, 0.70), (involvement, 0.30))
    return clamp(base + spread(profile.source_id, 8), low=1.0, high=99.0)


#: How much each ability counts towards a player's transfer value. Kicking is
#: weighted low on purpose: it's the one ability a whole position group can
#: legitimately have none of, and pricing it higher just makes every forward
#: cheap.
VALUE_WEIGHTS = {
    "attacking": 0.20,
    "defensive": 0.20,
    "kicking": 0.06,
    "discipline": 0.08,
    "consistency": 0.16,
    "fitness": 0.13,
    "form": 0.17,
}

#: Overall ratings the value curve spans. Nobody sinks below the low end once
#: the baselines are applied, and the best season in the league lands near the
#: high end - so these are the real observed bounds, not the theoretical 0-100.
VALUE_FLOOR_RATING = 35.0
VALUE_CEILING_RATING = 80.0
#: Price of a player at the ceiling, in millions.
MAX_VALUE = 18.0


def market_value(ratings: dict[str, float], age: int | None) -> float:
    """A transfer price in millions, from the seven abilities and age.

    Deliberately non-linear: a 75-rated player costs far more than twice a
    50-rated one, which is what makes a squad budget an interesting
    constraint rather than an exercise in buying the most players. Squaring
    the quality term does that.

    Age then scales the result - a 22-year-old carries resale value a
    34-year-old doesn't - and the floor is applied last, so the oldest player
    in the league still has a price.
    """
    overall = sum(ratings[key] * weight for key, weight in VALUE_WEIGHTS.items())
    span = VALUE_CEILING_RATING - VALUE_FLOOR_RATING
    quality = clamp((overall - VALUE_FLOOR_RATING) / span, 0.0, 1.0) ** 2.0

    if age is None:
        age_factor = 1.0
    elif age <= 21:
        age_factor = 1.05
    elif age <= 29:
        age_factor = 1.0
    else:
        age_factor = max(0.55, 1.0 - 0.07 * (age - 29))

    return round(max(0.2, MAX_VALUE * quality * age_factor), 1)


def rate(profile: ScrapedPlayerProfile, position: str) -> dict[str, float]:
    """Every rating for one player, keyed by `Player` field name.

    The order matters: `currentForm` is built from the finished attacking and
    defensive ratings, and `value` from all seven.
    """
    marks = benchmarks_for(position)
    base = baselines_for(position)
    rates = Per80.from_profile(profile)
    minutes = float(profile.minutes_played)

    attacking = shrink(attacking_ability(rates, marks), base.attacking, minutes)
    defensive = shrink(
        defensive_ability(rates, marks, profile.stats.defence.tackle_success_pct),
        base.defensive,
        minutes,
    )
    measured_kicking = kicking_ability(rates, marks, profile)
    if measured_kicking is None:
        # Never kicked, so there is nothing to measure - the baseline stands,
        # scattered a little so a pack doesn't read as one repeated number.
        kicking = clamp(base.kicking + spread(profile.source_id, 6, salt=7))
    else:
        kicking = shrink(measured_kicking, base.kicking, minutes)
    discipline = shrink(discipline_rating(rates, marks), base.discipline, minutes)
    consistency = shrink(
        consistency_rating(rates, marks, profile), base.consistency, minutes
    )
    # Fitness and form aren't shrunk: both are built from minutes and age
    # rather than from rates, so a small sample is already reflected in them.
    fitness = fitness_rating(profile)
    form = form_rating(profile, attacking, defensive)

    return {
        "attacking": attacking,
        "defensive": defensive,
        "kicking": kicking,
        "discipline": discipline,
        "consistency": consistency,
        "fitness": fitness,
        "form": form,
    }
