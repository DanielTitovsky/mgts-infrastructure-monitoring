FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /usr/local/bin/

ENV HOME=/home/workbench \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --extra ui --extra inference --no-install-project

COPY mgts_data_pipeline ./mgts_data_pipeline
COPY notebooks ./notebooks
COPY container-entrypoint.sh /usr/local/bin/marimo-container-entrypoint

RUN uv sync --locked --no-dev --extra ui --extra inference \
    && groupadd --system --gid 10001 workbench \
    && useradd --system --uid 10001 --gid workbench --create-home --home-dir /home/workbench workbench \
    && mkdir -p /data/archive /data/hub /data/notebooks /data/output /models \
    && chown -R workbench:workbench /data /home/workbench \
    && chmod 0755 /usr/local/bin/marimo-container-entrypoint

# OpenCV's wheel needs these shared libraries even for CPU-only inference.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libxcb1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && uv run --no-sync python -c "from ultralytics import YOLO"

COPY marimo.toml /home/workbench/.marimo.toml
USER 10001:10001
EXPOSE 8790
ENTRYPOINT ["/usr/local/bin/marimo-container-entrypoint"]
