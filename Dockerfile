FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE glama.json ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && pip install .

ENTRYPOINT ["weather-edge-mcp"]
