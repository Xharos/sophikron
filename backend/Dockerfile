FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app

RUN pip install --no-cache-dir .

FROM base AS test

RUN pip install --no-cache-dir ".[dev]"

COPY backend/tests ./tests

CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime

RUN useradd --system --uid 10001 --create-home appuser

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "5"]
