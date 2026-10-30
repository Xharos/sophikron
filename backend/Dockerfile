FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic

ARG SOPHIKRON_BUILD_REVISION=unknown
RUN printf '%s' "$SOPHIKRON_BUILD_REVISION" > app/core/revision.txt

RUN pip install --no-cache-dir .

RUN useradd --system --uid 10001 --create-home appuser
RUN mkdir -p /var/lib/sophikron/documents && chown appuser:appuser /var/lib/sophikron/documents && chmod 700 /var/lib/sophikron/documents

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "5"]
