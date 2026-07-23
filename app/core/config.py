from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class Settings(BaseSettings):
    """Runtime configuration, overridable via URC_* env vars or a .env file."""

    model_config = SettingsConfigDict(
        env_prefix="URC_", env_file=".env", extra="ignore"
    )

    # The stats site is a client-rendered SPA; this GraphQL endpoint is the
    # source it reads from. See app/scraper/client.py for why the browser-ish
    # headers below are not optional.
    graphql_url: str = "https://www.unitedrugby.com/graphql"
    stats_base_url: str = "https://stats.unitedrugby.com"

    # Where `scripts/export_players.py` writes the converted, API-shaped
    # players, and where `GET /players` reads them from. Scraping takes ~30s
    # for the league, so the API serves a file rather than the live site;
    # when the file is absent it falls back to a placeholder record.
    players_file: Path = Path("data/players.json")

    user_agent: str = DEFAULT_USER_AGENT
    # Browser TLS fingerprint curl_cffi impersonates; see app/scraper/client.py.
    impersonate: str = "chrome"
    request_timeout: float = 30.0
    max_retries: int = 3
    retry_backoff: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
