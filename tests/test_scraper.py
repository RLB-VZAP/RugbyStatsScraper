import pytest

from app.core.config import Settings
from app.scraper import GraphQLClient, ScraperError, URCScraper
from app.scraper.slugs import club_slug, player_slug

SETTINGS = Settings(max_retries=2, retry_backoff=0)

CLUBS_RESPONSE = {
    "clubs": [
        {"id": 1641, "team_name": "Edinburgh Rugby"},
        {"id": 1527, "team_name": "Hollywoodbets Sharks"},
    ],
    "clubThemeSettings": {
        "clubs": [
            {"id": 1641, "fullName": "Edinburgh", "shortName": "EDI"},
            {"id": 1527, "fullName": "Hollywoodbets Sharks", "shortName": "SHA"},
        ]
    },
}

PLAYERS_RESPONSE = {
    "players": [
        {
            "id": 1,
            "club_id": 1641,
            "player_data": {
                "firstName": "Ben",
                "lastName": "Van Der Merwe",
                "knownName": "Ben van der Merwe",
                "dob": "1998-04-19T12:00:00.000Z",
                "birthplace": "Edinburgh",
                "joinDate": "2021-07-01",
                "leaveDate": None,
                "height": {"heightM": 1.85},
                "weight": {"weightKg": 98},
                "normalPosition": {"name": "flanker"},
                "countryOfBirth": {"name": "Scotland"},
            },
        },
        {
            "id": 2,
            "club_id": 1527,
            "player_data": {
                "firstName": "Siya",
                "lastName": "Masuku",
                "knownName": "Siya Masuku",
                "dob": None,
                "birthplace": None,
                "joinDate": None,
                "leaveDate": None,
                "height": None,
                "weight": None,
                "normalPosition": {"name": "fly-half"},
                "countryOfBirth": None,
            },
        },
        # Belongs to a club the clubs query didn't return - must be dropped
        # rather than crash the run.
        {"id": 3, "club_id": 9999, "player_data": {"firstName": "X", "lastName": "Y"}},
        # Unusable name - skipped.
        {"id": 4, "club_id": 1527, "player_data": {"firstName": "", "lastName": "Nobody"}},
    ]
}


class FakeResponse:
    """Stands in for a curl_cffi response."""

    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if not 200 <= self.status_code < 400:
            raise RuntimeError(f"HTTP Error {self.status_code}")

    def json(self):
        return self._body

    async def close(self):
        pass


class FakeSession:
    """Answers each POST from a canned {query fragment: data} map."""

    def __init__(self, responses=None, handler=None):
        self._responses = responses or {}
        self._handler = handler
        self.requests = []

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self._handler is not None:
            return self._handler(url, kwargs)
        query = kwargs["json"]["query"]
        for marker, payload in self._responses.items():
            if marker in query:
                return FakeResponse({"data": payload})
        return FakeResponse({"errors": [{"message": "unmapped query"}]}, 404)

    async def close(self):
        pass


def _scraper(responses):
    client = GraphQLClient(SETTINGS, session=FakeSession(responses))
    return client, URCScraper(client, SETTINGS)


class TestSlugs:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Hollywoodbets Sharks", "hollywoodbets-sharks"),
            ("Edinburgh", "edinburgh"),
            ("Dragons RFC", "dragons-rfc"),
            ("DHL Stormers", "dhl-stormers"),
            ("Zebre Parma", "zebre-parma"),
            ("  Vodacom  Bulls  ", "vodacom-bulls"),
        ],
    )
    def test_club_slug(self, name, expected):
        assert club_slug(name) == expected

    @pytest.mark.parametrize(
        ("first", "last", "expected"),
        [
            ("Manie", "Libbok", "manie-libbok"),
            ("Ben", "Van Der Merwe", "ben-van-der-merwe"),
            ("Jean-Luc", "du Preez", "jean-luc-du-preez"),
            # Punctuation survives - the site doesn't strip it either.
            ("Jimmy", "O'Brien", "jimmy-o'brien"),
            # The site splits on a literal "%20" as well as real whitespace.
            ("Marnus", "van%20der Berg", "marnus-van-der-berg"),
        ],
    )
    def test_player_slug(self, first, last, expected):
        assert player_slug(first, last) == expected


class TestFetchClubs:
    @pytest.mark.asyncio
    async def test_uses_theme_name_for_slug_and_builds_urls(self):
        client, scraper = _scraper({"clubs": CLUBS_RESPONSE})
        async with client:
            clubs = await scraper.fetch_clubs()

        assert [club.source_id for club in clubs] == [1527, 1641]

        edinburgh = clubs[1]
        # The API calls it "Edinburgh Rugby", the site slugs it "edinburgh".
        assert edinburgh.name == "Edinburgh"
        assert edinburgh.slug == "edinburgh"
        assert edinburgh.url == "https://stats.unitedrugby.com/clubs/edinburgh"
        assert (
            edinburgh.players_url
            == "https://stats.unitedrugby.com/clubs/edinburgh/players"
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_api_name_when_theme_entry_missing(self):
        response = {
            "clubs": [{"id": 4471, "team_name": "Cardiff Rugby"}],
            "clubThemeSettings": {"clubs": []},
        }
        client, scraper = _scraper({"clubs": response})
        async with client:
            clubs = await scraper.fetch_clubs()

        assert clubs[0].slug == "cardiff-rugby"

    @pytest.mark.asyncio
    async def test_empty_club_list_is_an_error(self):
        client, scraper = _scraper({"clubs": {"clubs": [], "clubThemeSettings": None}})
        async with client:
            with pytest.raises(ScraperError):
                await scraper.fetch_clubs()


class TestFetchRosters:
    @pytest.mark.asyncio
    async def test_groups_players_and_builds_stats_urls(self):
        client, scraper = _scraper(
            {"clubs": CLUBS_RESPONSE, "players {": PLAYERS_RESPONSE}
        )
        async with client:
            rosters = await scraper.fetch_rosters()

        by_slug = {roster.club.slug: roster for roster in rosters}
        assert set(by_slug) == {"hollywoodbets-sharks", "edinburgh"}

        player = by_slug["edinburgh"].players[0]
        assert player.slug == "ben-van-der-merwe"
        assert (
            player.stats_url
            == "https://stats.unitedrugby.com/clubs/edinburgh/ben-van-der-merwe"
        )
        assert player.club_source_id == 1641
        assert player.position == "flanker"
        assert player.height_m == 1.85
        assert player.weight_kg == 98

    @pytest.mark.asyncio
    async def test_drops_unknown_clubs_and_unusable_names(self):
        client, scraper = _scraper(
            {"clubs": CLUBS_RESPONSE, "players {": PLAYERS_RESPONSE}
        )
        async with client:
            rosters = await scraper.fetch_rosters()

        ids = {player.source_id for roster in rosters for player in roster.players}
        assert ids == {1, 2}

    @pytest.mark.asyncio
    async def test_missing_optional_fields_are_none(self):
        client, scraper = _scraper(
            {"clubs": CLUBS_RESPONSE, "players {": PLAYERS_RESPONSE}
        )
        async with client:
            rosters = await scraper.fetch_rosters()

        sharks = next(r for r in rosters if r.club.slug == "hollywoodbets-sharks")
        player = sharks.players[0]
        assert player.height_m is None
        assert player.weight_kg is None
        assert player.country_of_birth is None
        assert player.position == "fly-half"


class TestClient:
    @pytest.mark.asyncio
    async def test_graphql_errors_raise(self):
        session = FakeSession(
            handler=lambda url, kwargs: FakeResponse({"errors": [{"message": "boom"}]})
        )
        client = GraphQLClient(SETTINGS, session=session)
        async with client:
            with pytest.raises(ScraperError, match="boom"):
                await client.execute("query { clubs { id } }")

    @pytest.mark.asyncio
    async def test_retries_then_gives_up_on_http_errors(self):
        session = FakeSession(handler=lambda url, kwargs: FakeResponse({}, 503))
        client = GraphQLClient(SETTINGS, session=session)
        async with client:
            with pytest.raises(ScraperError, match="after 2 attempts"):
                await client.execute("query { clubs { id } }")

        assert len(session.requests) == SETTINGS.max_retries

    @pytest.mark.asyncio
    async def test_recovers_after_a_transient_failure(self):
        attempts = []

        def handler(url, kwargs):
            attempts.append(url)
            if len(attempts) == 1:
                return FakeResponse({}, 502)
            return FakeResponse({"data": {"clubs": []}})

        client = GraphQLClient(SETTINGS, session=FakeSession(handler=handler))
        async with client:
            assert await client.execute("query { clubs { id } }") == {"clubs": []}
        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_sends_headers_the_endpoint_requires(self):
        session = FakeSession(handler=lambda url, kwargs: FakeResponse({"data": {}}))
        client = GraphQLClient(SETTINGS, session=session)
        async with client:
            await client.execute("query { clubs { id } }")

        headers = session.requests[0][1]["headers"]
        assert headers["Origin"] == "https://stats.unitedrugby.com"
        assert headers["Referer"] == "https://stats.unitedrugby.com/"
        assert "Mozilla" in headers["User-Agent"]

    @pytest.mark.asyncio
    async def test_execute_outside_context_manager_raises(self):
        client = GraphQLClient(SETTINGS)
        with pytest.raises(ScraperError):
            await client.execute("query { clubs { id } }")
