# syntax=docker/dockerfile:1

# Rugby Stats Scraper - FastAPI service image.
#
#   docker build -t rugby-stats-scraper .
#   docker run --rm -p 8000:8000 rugby-stats-scraper
#
# Coolify (Dockerfile build pack) reads the port from EXPOSE below; the app also
# honours an optional PORT env var if you'd rather set it there.

FROM python:3.13-slim

# Predictable, lean Python inside a container.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so this layer caches across app-code changes.
# lxml, curl_cffi, pydantic-core etc. ship manylinux wheels, so no compiler or
# system libs are needed on top of the slim base.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code. scripts/ is included so an operator can regenerate the
# player export from inside the container:
#   python -m scripts.export_players -o /app/data/players.json
COPY app ./app
COPY scripts ./scripts

# GET /players reads this file. data/ is gitignored and not in the repo, so a
# fresh build won't contain it - create the dir and let the API fall back to its
# placeholder record until the file is supplied (mount a volume at /app/data, or
# run the export above). See README "API".
RUN mkdir -p /app/data
ENV URC_PLAYERS_FILE=/app/data/players.json

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Simple liveness probe; /players always returns 200 (placeholder fallback).
# Uses stdlib so the slim image needs no curl/wget.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/players', timeout=4).status == 200 else 1)"

# Shell form so ${PORT} (optional override) expands; defaults to 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]