FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ANNUAL_REPORT_DATA_DIR=/data/reports \
    OPENHARNESS_CONFIG_DIR=/data/config \
    OPENHARNESS_DATA_DIR=/data/openharness

WORKDIR /app
COPY . .
RUN python -m pip install --no-cache-dir uv==0.13.6 \
    && uv sync --locked --extra reports --no-dev --no-editable --no-cache \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /data
USER app

EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3).read()"

CMD ["/app/.venv/bin/annual-report-assistant", "--host", "0.0.0.0", "--port", "8787"]
