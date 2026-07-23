import pytest

from app.models.player import Player
from app.processing import (
    POSITIONS,
    club_id,
    normalise_position,
    position_id,
    profile_to_player,
    profiles_to_players,
)
from app.processing.positions import POSITION_BASELINES, POSITION_BENCHMARKS
from app.processing.ratings import (
    Per80,
    band,
    market_value,
    rate,
    scale,
    shrink,
    spread,
)
from app.scraper.models import (
    AttackStats,
    DefenceStats,
    DisciplineStats,
    KickingStats,
    PlayerInfo,
    PlayerStats,
    ScrapedPlayerProfile,
)

RATING_FIELDS = (
    "attacking_ability",
    "defensive_ability",
    "kicking_ability",
    "discipline",
    "consistency",
    "fitness",
    "current_form",
)


def profile(
    *,
    source_id: int = 219771,
    position: str = "fly-half",
    age: int = 27,
    matches: int = 16,
    minutes: int = 1142,
    attack: AttackStats | None = None,
    defence: DefenceStats | None = None,
    kicking: KickingStats | None = None,
    discipline: DisciplineStats | None = None,
) -> ScrapedPlayerProfile:
    """A scraped profile, defaulting to Handre Pollard's real 2025/26 season."""
    return ScrapedPlayerProfile(
        source_id=source_id,
        slug="handre-pollard",
        club_source_id=5586,
        club_slug="vodacom-bulls",
        stats_url="https://stats.unitedrugby.com/clubs/vodacom-bulls/handre-pollard",
        season_id="202501" if minutes else None,
        season_name="2025-26" if minutes else None,
        matches_played=matches,
        minutes_played=minutes,
        info=PlayerInfo(name="Handre", surname="Pollard", age=age, position=position),
        stats=PlayerStats(
            attack=attack
            or AttackStats(
                points_scored=129,
                tries_scored=3,
                assists=4,
                clean_breaks=6,
                defenders_beaten=20,
                carries=102,
                metres_gained=319,
                offloads=8,
            ),
            defence=defence
            or DefenceStats(
                number_of_tackles=73,
                missed_tackles=30,
                tackle_success_pct=64.6,
                turnovers_won=3,
                turnovers_lost=21,
            ),
            kicking=kicking
            or KickingStats(
                penalties_scored=12,
                conversions_scored=39,
                drop_goals=0,
                kicks_from_hand=90,
                kick_success_pct=71.0,
            ),
            discipline=discipline
            or DisciplineStats(yellow_cards=1, red_cards=0, penalties_conceded=3),
        ),
    )


class TestPositions:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # What the source actually sends.
            ("fly-half", "fly-half"),
            ("no. 8", "number-8"),
            ("scrum-half", "scrum-half"),
            # Variants, so a renaming upstream doesn't silently unrate anyone.
            ("Loosehead Prop", "prop"),
            ("  SECOND ROW  ", "lock"),
            ("out-half", "fly-half"),
            ("winger", "wing"),
            ("full back", "fullback"),
            ("center", "centre"),
            # Neither known nor guessable.
            ("hovercraft pilot", "unknown"),
            (None, "unknown"),
            ("", "unknown"),
        ],
    )
    def test_normalise(self, raw, expected):
        assert normalise_position(raw) == expected

    def test_every_position_has_benchmarks_and_baselines(self):
        assert set(POSITION_BENCHMARKS) == set(POSITIONS)
        assert set(POSITION_BASELINES) == set(POSITIONS)

    def test_no_benchmark_is_zero(self):
        # They're divisors in `scale()`.
        for marks in POSITION_BENCHMARKS.values():
            assert all(value > 0 for value in vars(marks).values())

    def test_ids_are_stable_distinct_and_alias_insensitive(self):
        assert position_id("fly-half") == position_id("out-half")
        assert position_id("prop") != position_id("hooker")
        assert club_id("edinburgh") == club_id("  Edinburgh ")
        assert club_id("edinburgh") != club_id("leinster")


class TestScales:
    def test_benchmark_scores_fifty(self):
        assert scale(8.0, 8.0) == pytest.approx(50.0)

    def test_zero_scores_zero_and_nothing_reaches_a_hundred(self):
        assert scale(0.0, 8.0) == 0.0
        assert scale(10_000.0, 8.0) < 100.0

    def test_monotonic(self):
        scores = [scale(rate, 8.0) for rate in (1, 4, 8, 16, 40)]
        assert scores == sorted(scores)

    def test_band_clamps_both_ends(self):
        assert band(40.0, 50.0, 100.0) == 0.0
        assert band(75.0, 50.0, 100.0) == pytest.approx(50.0)
        assert band(120.0, 50.0, 100.0) == 100.0

    def test_shrink_falls_back_to_baseline_without_minutes(self):
        assert shrink(90.0, 40.0, minutes=0) == 40.0

    def test_shrink_splits_evenly_at_three_matches(self):
        assert shrink(90.0, 40.0, minutes=240) == pytest.approx(65.0)

    def test_shrink_barely_moves_a_full_season(self):
        assert shrink(90.0, 40.0, minutes=1400) == pytest.approx(90.0, abs=8.0)

    def test_spread_stays_in_range_and_is_stable(self):
        offsets = [spread(source_id, 8) for source_id in range(500)]
        assert all(-8 <= offset <= 8 for offset in offsets)
        assert set(offsets) == set(range(-8, 9))
        assert spread(219771, 8) == spread(219771, 8)

    def test_salt_stops_two_uses_moving_in_lockstep(self):
        assert any(spread(pid, 6, salt=7) != spread(pid, 6) for pid in range(500))


class TestPer80:
    def test_rates_are_scaled_to_eighty_minutes(self):
        rates = Per80.from_profile(profile(minutes=160))
        # 102 carries in two matches' worth of minutes = 51 per 80.
        assert rates.carries == pytest.approx(51.0)

    def test_no_minutes_gives_no_rates_rather_than_dividing_by_zero(self):
        rates = Per80.from_profile(profile(minutes=0, matches=0))
        assert rates.carries == 0.0
        assert rates.tackles == 0.0

    def test_tries_and_assists_are_pooled(self):
        rates = Per80.from_profile(profile(minutes=80))
        assert rates.scoring == pytest.approx(7.0)  # 3 tries + 4 assists

    def test_a_red_card_counts_triple(self):
        rates = Per80.from_profile(
            profile(
                minutes=80,
                discipline=DisciplineStats(yellow_cards=1, red_cards=1),
            )
        )
        assert rates.cards == pytest.approx(4.0)


class TestConversion:
    def test_produces_a_valid_player(self):
        player = profile_to_player(profile())

        assert isinstance(player, Player)
        assert player.player_name == "Handre Pollard"
        assert player.club_id == club_id("vodacom-bulls")
        assert player.position_id == position_id("fly-half")
        assert player.value > 0

    def test_every_rating_is_an_int_in_range(self):
        player = profile_to_player(profile())
        for field in RATING_FIELDS:
            value = getattr(player, field)
            assert isinstance(value, int)
            assert 0 <= value <= 100

    def test_is_deterministic(self):
        assert profile_to_player(profile()) == profile_to_player(profile())

    def test_a_goal_kicking_fly_half_outkicks_a_prop_who_never_kicks(self):
        kicker = profile_to_player(profile())
        prop = profile_to_player(
            profile(
                position="prop",
                kicking=KickingStats(),
                attack=AttackStats(carries=90, metres_gained=120),
            )
        )
        assert kicker.kicking_ability > prop.kicking_ability

    def test_a_forward_who_never_kicks_keeps_the_positional_baseline(self):
        # Not measurable is not the same as bad - the pack shouldn't all be
        # rated single digits for an ability nobody ever asks them to use.
        prop = profile_to_player(profile(position="prop", kicking=KickingStats()))
        assert prop.kicking_ability >= 10

    def test_cards_and_penalties_cost_discipline(self):
        clean = profile_to_player(
            profile(discipline=DisciplineStats(penalties_conceded=1))
        )
        dirty = profile_to_player(
            profile(
                discipline=DisciplineStats(
                    penalties_conceded=18, yellow_cards=3, red_cards=1
                )
            )
        )
        assert dirty.discipline < clean.discipline

    def test_more_metres_means_more_attacking_ability(self):
        quiet = profile_to_player(
            profile(attack=AttackStats(carries=100, metres_gained=100))
        )
        dangerous = profile_to_player(
            profile(
                attack=AttackStats(
                    carries=100,
                    metres_gained=900,
                    clean_breaks=20,
                    defenders_beaten=40,
                    tries_scored=9,
                )
            )
        )
        assert dangerous.attacking_ability > quiet.attacking_ability

    def test_positions_are_rated_against_their_own_position(self):
        # An identical stat line is elite for a prop and ordinary for a wing.
        line = AttackStats(carries=80, metres_gained=300, defenders_beaten=12)
        prop = profile_to_player(profile(position="prop", attack=line))
        wing = profile_to_player(profile(position="wing", attack=line))
        assert prop.attacking_ability > wing.attacking_ability

    def test_a_player_with_no_minutes_still_gets_plausible_ratings(self):
        # 134 of 897 squad members never played; they can't be all-zero.
        benched = profile_to_player(profile(minutes=0, matches=0))
        for field in RATING_FIELDS:
            assert 10 <= getattr(benched, field) <= 95
        assert benched.value >= 0.2

    def test_a_small_sample_is_pulled_back_towards_the_baseline(self):
        cameo = profile_to_player(
            profile(
                matches=1,
                minutes=20,
                attack=AttackStats(carries=12, metres_gained=140, tries_scored=2),
            )
        )
        # Exactly the same output per 80 minutes, sustained for a season.
        sustained = profile_to_player(
            profile(
                matches=15,
                minutes=1200,
                attack=AttackStats(carries=720, metres_gained=8400, tries_scored=120),
            )
        )
        assert cameo.attacking_ability < sustained.attacking_ability
        # That rate on its own scores ~99. Twenty minutes doesn't earn it.
        assert cameo.attacking_ability < 65

    def test_names_survive_a_missing_half(self):
        only_surname = profile()
        only_surname.info.name = ""
        assert profile_to_player(only_surname).player_name == "Pollard"


class TestValue:
    def test_rises_with_overall_rating(self):
        weak = dict.fromkeys(rate(profile(), "fly-half"), 30.0)
        strong = dict.fromkeys(rate(profile(), "fly-half"), 85.0)
        assert market_value(strong, 26) > market_value(weak, 26)

    def test_is_not_linear(self):
        levels = (40, 60, 80)
        scores = {
            level: dict.fromkeys(rate(profile(), "fly-half"), level) for level in levels
        }
        low, mid, high = (market_value(scores[level], 26) for level in levels)
        assert (high - mid) > (mid - low)

    def test_veterans_are_discounted(self):
        scores = dict.fromkeys(rate(profile(), "fly-half"), 70.0)
        assert market_value(scores, 35) < market_value(scores, 26)

    def test_never_falls_to_zero(self):
        assert market_value(dict.fromkeys(rate(profile(), "prop"), 0.0), 38) >= 0.2


class TestBatch:
    def test_sorted_by_value_descending(self):
        players = profiles_to_players(
            [
                profile(source_id=1, minutes=0, matches=0),
                profile(source_id=2),
                profile(
                    source_id=3,
                    attack=AttackStats(carries=110, metres_gained=800, tries_scored=8),
                ),
            ]
        )
        values = [player.value for player in players]
        assert values == sorted(values, reverse=True)

    def test_converts_every_profile(self):
        assert len(profiles_to_players([profile(source_id=i) for i in range(5)])) == 5
