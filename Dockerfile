FROM node:22-alpine AS assets
WORKDIR /build
COPY package.json package-lock.json tailwind.config.cjs ./
RUN npm ci --ignore-scripts
COPY scripts/build-assets.cjs ./scripts/build-assets.cjs
COPY app/templates ./app/templates
COPY app/static ./app/static
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SKIP_DOTENV=1 \
    DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir -p /app/data/exports /app/data/backups \
    && chown -R app:app /app/data
COPY --chown=app:app app ./app
COPY --chown=app:app --from=assets /build/app/static ./app/static
COPY --chown=app:app scripts/backup_sqlite.py ./scripts/backup_sqlite.py
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4).read()"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
