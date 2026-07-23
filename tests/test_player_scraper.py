import pytest

from app.core.config import Settings
from app.scraper import GraphQLClient, PlayerScraper, ScrapedClub, ScraperError
from app.scraper.players import (
    _format_birthday,
    _format_height,
    _format_weight,
)
from tests.test_scraper import FakeSession

SETTINGS = Settings(max_retries=2, retry_backoff=0)

CLUB = ScrapedClub(
    source_id=5586,
    name="Vodacom Bulls",
    slug="vodacom-bulls",
    url="https://stats.unitedrugby.com/clubs/vodacom-bulls",
    players_url="https://stats.unitedrugby.com/clubs/vodacom-bulls/players",
)

SEASONS_RESPONSE = {
    "seasonsConfiguration": {
        "defaultSeasonForRound": "202601",
        "defaultSeasonExceptRound": "202501",
        # Arrives as a bare string even though a sibling field of the same
        # declared type arrives as a list.
        "excludeFromFilter": "202601",
        "seasons": [
            {"key": "202601", "label": "2026/27"},
            {"key": "202501", "label": "2025/26"},
            {"key": "202401", "label": "2024/25"},
        ],
    }
}

SQUAD_RESPONSE = {
    "playerThemeSettings": {
        "squads": [
            {
                "currentClub": "5586",
                "squad": [
                    {
                        "playerId": 219771,
                        "knownName": "handre-pollard",
                        "playerFirstName": "Handre",
                        "playerLastName": "Pollard",
                        "playerPosition": "fly-half",
                        "playerAge": 32,
                        "dateOfBirth": "1994-03-11",
                        "birthcountry": "South Africa",
                        "nationalTeam": "South Africa",
                        "playerHeight": "6'2",
                        "playerHeightCm": 188,
                        "playerWeight": "98",
                        "headshots": "https://cdn.example/pollard.webp",
                        "urcDebut": "2025-09-05",
                    },
                    # No stats row for the requested season - still a profile.
                    {
                        "playerId": 100317,
                        "knownName": "manuel-rass",
                        "playerFirstName": "Manuel",
                        "playerLastName": "Rass",
                        "playerPosition": "centre",
                        "playerAge": 28,
                        "dateOfBirth": "1998-04-19",
                        "birthcountry": "South Africa",
                        "nationalTeam": None,
                        "playerHeight": "5'9",
                        "playerHeightCm": 175,
                        "playerWeight": "86",
                        "headshots": None,
                        "urcDebut": "2025-09-02",
                    },
                    # Nameless - dropped rather than crashing the run.
                    {"playerId": 999, "playerFirstName": "", "playerLastName": ""},
                    {"playerId": None, "playerFirstName": "No", "playerLastName": "Id"},
                ],
            }
        ]
    }
}

STATS_RESPONSE = {
    "playerseasonstats": [
        {
            "player_id": 219771,
            "season_id": "202501",
            "season_name": "2025-26",
            "team_id": 5586,
            "team_name": "Vodacom Bulls",
            "player_stats": {
                "playerStats": {
                    "attack": {
                        "carries": 102,
                        "cleanBreak": 6,
                        "defenderBeaten": 20,
                        "metresMade": 319,
                        "offload": 8,
                        "tryAssist": 4,
                        "errors": 21,
                    },
                    "defence": {
                        "tackle": 73,
                        "missedTackle": 30,
                        "percentTackleMade": 64.6,
                        "turnoverWon": 3,
                    },
                    "discipline": {
                        "lineoutOffence": None,
                        "penaltyConceded": 3,
                        "scrumOffence": None,
                        "yellowCard": 1,
                        "redCard": None,
                    },
                    "kicking": {"kicksInPlay": 90},
                    "lineout": {
                        "lineoutSteals": 1,
                        "lineoutThrowsLost": None,
                        "lineoutThrowsWon": None,
                        "percentLineoutsWon": None,
                    },
                    "scoring": {
                        "points": 129,
                        "tryScored": 3,
                        "conversion": 39,
                        "percentGoals": 71,
                        "penaltyGoal": 12,
                        "dropGoal": None,
                        "appearances": 16,
                        "minutesPlayed": 1142,
                    },
                }
            },
        }
    ]
}

RESPONSES = {
    "seasonsConfiguration": SEASONS_RESPONSE,
    "playerThemeSettings": SQUAD_RESPONSE,
    "playerseasonstats": STATS_RESPONSE,
}


def _scraper(responses=None):
    session = FakeSession(responses if responses is not None else RESPONSES)
    client = GraphQLClient(SETTINGS, session=session)
    return client, PlayerScraper(client, SETTINGS), session


class TestFormatters:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1994-03-11", "11-03-1994"),
            ("1998-04-19T12:00:00.000Z", "19-04-1998"),
            (None, None),
            ("", None),
            ("not-a-date", None),
        ],
    )
    def test_birthday(self, raw, expected):
        assert _format_birthday(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("6'2", "6'2\""), ("5'9\"", "5'9\""), (None, None), ("  ", None)],
    )
    def test_height(self, raw, expected):
        assert _format_height(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("98", "98 KG"), ("98 KG", "98 KG"), (None, None), ("", None)],
    )
    def test_weight(self, raw, expected):
        assert _format_weight(raw) == expected


class TestSeasons:
    @pytest.mark.asyncio
    async def test_hides_excluded_season_like_the_dropdown_does(self):
        client, scraper, _ = _scraper()
        async with client:
            seasons = await scraper.fetch_seasons()

        assert [season.key for season in seasons] == ["202501", "202401"]
        assert seasons[0].label == "2025/26"

    @pytest.mark.asyncio
    async def test_include_hidden_returns_the_raw_list(self):
        client, scraper, _ = _scraper()
        async with client:
            seasons = await scraper.fetch_seasons(include_hidden=True)

        assert [season.key for season in seasons] == ["202601", "202501", "202401"]

    @pytest.mark.asyncio
    async def test_default_season(self):
        client, scraper, _ = _scraper()
        async with client:
            assert await scraper.default_season_id() == "202501"

    @pytest.mark.asyncio
    async def test_no_seasons_is_an_error(self):
        client, scraper, _ = _scraper(
            {"seasonsConfiguration": {"seasonsConfiguration": {"seasons": []}}}
        )
        async with client:
            with pytest.raises(ScraperError):
                await scraper.fetch_seasons()


class TestClubProfiles:
    @pytest.mark.asyncio
    async def test_banner_maps_onto_player_info(self):
        client, scraper, _ = _scraper()
        async with client:
            profiles = await scraper.fetch_club_profiles(CLUB, "202501")

        pollard = next(p for p in profiles if p.source_id == 219771)
        info = pollard.info
        assert info.name == "Handre"
        assert info.surname == "Pollard"
        assert info.age == 32
        assert info.birthday == "11-03-1994"
        assert info.height == "6'2\""
        assert info.weight == "98 KG"
        assert info.birth_country == "South Africa"
        assert info.national_team == "South Africa"
        # The banner's third column, the `font-urcHand` element.
        assert info.position == "fly-half"
        assert info.image_url == "https://cdn.example/pollard.webp"

    @pytest.mark.asyncio
    async def test_stats_panels_map_onto_the_page(self):
        client, scraper, _ = _scraper()
        async with client:
            profiles = await scraper.fetch_club_profiles(CLUB, "202501")

        stats = next(p for p in profiles if p.source_id == 219771).stats

        assert stats.attack.points_scored == 129
        assert stats.attack.tries_scored == 3
        assert stats.attack.assists == 4
        assert stats.attack.clean_breaks == 6
        assert stats.attack.defenders_beaten == 20
        assert stats.attack.carries == 102
        assert stats.attack.metres_gained == 319
        assert stats.attack.offloads == 8

        assert stats.defence.number_of_tackles == 73
        assert stats.defence.missed_tackles == 30
        assert stats.defence.tackle_success_pct == 64.6
        assert stats.defence.turnovers_won == 3
        # Sits in the Defence panel but is `attack.errors` upstream.
        assert stats.defence.turnovers_lost == 21

        assert stats.kicking.penalties_scored == 12
        assert stats.kicking.conversions_scored == 39
        assert stats.kicking.drop_goals == 0
        assert stats.kicking.kicks_from_hand == 90
        assert stats.kicking.kick_success_pct == 71

        assert stats.discipline.yellow_cards == 1
        assert stats.discipline.red_cards == 0
        assert stats.discipline.penalties_conceded == 3
        assert stats.discipline.scrum_offences == 0
        assert stats.discipline.lineout_offences == 0

        assert stats.lineouts.lineouts_won == 0
        assert stats.lineouts.lineouts_lost == 0
        assert stats.lineouts.lineout_success_pct == 0
        assert stats.lineouts.lineouts_steals == 1

    @pytest.mark.asyncio
    async def test_appearances_and_minutes_come_from_scoring(self):
        client, scraper, _ = _scraper()
        async with client:
            profiles = await scraper.fetch_club_profiles(CLUB, "202501")

        pollard = next(p for p in profiles if p.source_id == 219771)
        assert pollard.matches_played == 16
        assert pollard.minutes_played == 1142
        assert pollard.season_id == "202501"
        assert pollard.season_name == "2025-26"

    @pytest.mark.asyncio
    async def test_player_without_a_stats_row_is_zeroed_not_dropped(self):
        client, scraper, _ = _scraper()
        async with client:
            profiles = await scraper.fetch_club_profiles(CLUB, "202501")

        rass = next(p for p in profiles if p.source_id == 100317)
        assert rass.season_id is None
        assert rass.matches_played == 0
        assert rass.stats.attack.carries == 0
        assert rass.stats.defence.tackle_success_pct == 0
        # The banner is still fully populated.
        assert rass.info.position == "centre"
        assert rass.info.national_team is None

    @pytest.mark.asyncio
    async def test_uses_the_sites_own_slug_for_the_stats_url(self):
        client, scraper, _ = _scraper()
        async with client:
            profiles = await scraper.fetch_club_profiles(CLUB, "202501")

        pollard = next(p for p in profiles if p.source_id == 219771)
        assert pollard.slug == "handre-pollard"
        assert (
            pollard.stats_url
            == "https://stats.unitedrugby.com/clubs/vodacom-bulls/handre-pollard"
        )
        assert pollard.club_source_id == 5586
        assert pollard.club_slug == "vodacom-bulls"

    @pytest.mark.asyncio
    async def test_drops_squad_members_with_no_name_or_id(self):
        client, scraper, _ = _scraper()
        async with client:
            profiles = await scraper.fetch_club_profiles(CLUB, "202501")

        assert {p.source_id for p in profiles} == {219771, 100317}

    @pytest.mark.asyncio
    async def test_costs_two_requests_per_club(self):
        client, scraper, session = _scraper()
        async with client:
            await scraper.fetch_club_profiles(CLUB, "202501")

        assert len(session.requests) == 2

    @pytest.mark.asyncio
    async def test_season_is_sent_as_an_int_list(self):
        client, scraper, session = _scraper()
        async with client:
            await scraper.fetch_club_profiles(CLUB, "202401")

        stats_call = next(
            kwargs
            for _, kwargs in session.requests
            if "playerseasonstats" in kwargs["json"]["query"]
        )
        variables = stats_call["json"]["variables"]
        assert variables["seasonId"] == [202401]
        assert sorted(variables["playerId"]) == [100317, 219771]

    @pytest.mark.asyncio
    async def test_defaults_to_the_current_season(self):
        client, scraper, session = _scraper()
        async with client:
            await scraper.fetch_club_profiles(CLUB)

        stats_call = next(
            kwargs
            for _, kwargs in session.requests
            if "playerseasonstats" in kwargs["json"]["query"]
        )
        assert stats_call["json"]["variables"]["seasonId"] == [202501]

    @pytest.mark.asyncio
    async def test_squad_query_is_scoped_to_the_club_id_as_a_string(self):
        client, scraper, session = _scraper()
        async with client:
            await scraper.fetch_squad(CLUB.source_id)

        variables = session.requests[0][1]["json"]["variables"]
        assert variables == {"currentClub": ["5586"]}


class TestFetchPlayer:
    @pytest.mark.asyncio
    async def test_returns_one_profile(self):
        client, scraper, _ = _scraper()
        async with client:
            profile = await scraper.fetch_player(CLUB, 219771, "202501")

        assert profile.info.surname == "Pollard"
        assert profile.stats.attack.points_scored == 129

    @pytest.mark.asyncio
    async def test_unknown_player_raises(self):
        client, scraper, _ = _scraper()
        async with client:
            with pytest.raises(ScraperError, match="not in vodacom-bulls"):
                await scraper.fetch_player(CLUB, 1, "202501")


class TestSerialisation:
    @pytest.mark.asyncio
    async def test_dump_by_alias_uses_the_sources_percent_keys(self):
        client, scraper, _ = _scraper()
        async with client:
            profiles = await scraper.fetch_club_profiles(CLUB, "202501")

        dumped = next(p for p in profiles if p.source_id == 219771).model_dump(
            by_alias=True
        )

        assert set(dumped["stats"]) == {
            "attack",
            "defence",
            "kicking",
            "discipline",
            "lineouts",
        }
        assert set(dumped["stats"]["attack"]) == {
            "points_scored",
            "tries_scored",
            "assists",
            "clean_breaks",
            "defenders_beaten",
            "carries",
            "metres_gained",
            "offloads",
        }
        assert dumped["stats"]["defence"]["tackle_success_%"] == 64.6
        assert dumped["stats"]["kicking"]["kick_success_%"] == 71
        assert dumped["stats"]["lineouts"]["lineout_success_%"] == 0
        assert set(dumped["info"]) == {
            "name",
            "surname",
            "age",
            "birthday",
            "height",
            "weight",
            "birth_country",
            "national_team",
            "position",
            "image_url",
        }
