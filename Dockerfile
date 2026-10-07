# syntax=docker/dockerfile:1
# One-command local run for judges: replay mode by default, no credentials needed.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

FROM python:3.12-slim-bookworm
RUN useradd --create-home --uid 10001 app && install -d -o app /data
COPY --from=builder --chown=app:app /app /app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    LOGIOPS_DB_PATH=/data/logiops.sqlite3 LOGIOPS_AGENT_MODE=replay
USER app
EXPOSE 8000
VOLUME /data
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2)"
CMD ["uvicorn", "logiops.api:app", "--host", "0.0.0.0", "--port", "8000"]
