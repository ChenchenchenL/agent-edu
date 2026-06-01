FROM python:3.11-slim

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG ALL_PROXY
ARG NO_PROXY
ARG http_proxy
ARG https_proxy
ARG all_proxy
ARG no_proxy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    ALL_PROXY=${ALL_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${http_proxy} \
    https_proxy=${https_proxy} \
    all_proxy=${all_proxy} \
    no_proxy=${no_proxy}

WORKDIR /app

COPY pyproject.toml alembic.ini README.md compose.yaml /app/
COPY alembic /app/alembic
COPY apps /app/apps
COPY ops /app/ops
COPY packages /app/packages
COPY tests /app/tests

RUN pip install --no-cache-dir -e .[dev]

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
