FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SHOPWATCH_DB=/data/shopwatch.db \
    SHOPWATCH_PORT=8477

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Runs unprivileged. /data is the volume mount point and must be writable by this user.
RUN useradd --system --uid 10001 --create-home shopwatch \
 && mkdir -p /data && chown -R shopwatch:shopwatch /data /app
USER shopwatch

EXPOSE 8477

# Hits the real endpoint, which touches the database, rather than checking the port is open.
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys,os;\
u='http://127.0.0.1:'+os.environ.get('SHOPWATCH_PORT','8477')+'/healthz';\
sys.exit(0 if urllib.request.urlopen(u,timeout=8).status==200 else 1)"

CMD ["sh", "-c", "python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port ${SHOPWATCH_PORT:-8477}"]
