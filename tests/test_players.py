import json

import pytest
from fastapi.testclient import TestClient

from app.api.players import load_players
from app.core.config import get_settings
from app.main import app

client = TestClient(app)

PLAYER_KEYS = {
    "clubId",
    "positionId",
    "playerName",
    "value",
    "attackingAbility",
    "defensiveAbility",
    "kickingAbility",
    "discipline",
    "consistency",
    "fitness",
    "currentForm",
}


@pytest.fixture(autouse=True)
def _clear_caches():
    """Both the settings and the loaded players are process-cached."""
    get_settings.cache_clear()
    load_players.cache_clear()
    yield
    get_settings.cache_clear()
    load_players.cache_clear()


@pytest.fixture
def no_export(monkeypatch, tmp_path):
    """Point the API at a file that doesn't exist, whatever the dev has run."""
    monkeypatch.setenv("URC_PLAYERS_FILE", str(tmp_path / "absent.json"))


def test_list_players_returns_camel_case_shape(no_export):
    response = client.get("/players")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1

    player = body[0]
    assert set(player.keys()) == PLAYER_KEYS


def test_falls_back_to_placeholder_data_when_nothing_is_exported(no_export):
    body = client.get("/players").json()

    assert [player["playerName"] for player in body] == ["Manie Libbok"]


def test_serves_the_exported_file_when_there_is_one(monkeypatch, tmp_path):
    export = tmp_path / "players.json"
    export.write_text(
        json.dumps(
            [
                {
                    "clubId": "11111111-1111-1111-1111-111111111111",
                    "positionId": "22222222-2222-2222-2222-222222222222",
                    "playerName": "Handre Pollard",
                    "value": 4.6,
                    "attackingAbility": 50,
                    "defensiveAbility": 36,
                    "kickingAbility": 61,
                    "discipline": 70,
                    "consistency": 76,
                    "fitness": 86,
                    "currentForm": 64,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("URC_PLAYERS_FILE", str(export))

    body = client.get("/players").json()

    assert [player["playerName"] for player in body] == ["Handre Pollard"]
    assert set(body[0].keys()) == PLAYER_KEYS
