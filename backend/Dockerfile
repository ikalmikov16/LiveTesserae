FROM python:3.12-slim

WORKDIR /app

# No apt layer: the Pillow manylinux wheels bundle libjpeg/zlib/libpng, so the
# libpng-dev/libjpeg-dev install that used to live here built nothing and only
# added image size and CVE surface.

# Requirements first so the dependency layer caches independently of app code.
# requirements-dev.txt (black) and requirements-s3.txt (aioboto3/boto3) are
# deliberately not installed — see the comments in those files.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
# scripts/ must be inside the image: render_chunks.py has to run within the
# compose network (it talks to postgres:5432 and writes the chunk volume), and
# init_mosaic.py seeds a fresh mosaic the same way.
COPY scripts/ ./scripts/

# Run as a non-root user, and create the chunk store owned by that user in the
# SAME layer.
#
# This ordering is load-bearing. Docker seeds a fresh named volume from whatever
# exists at that path in the image. If /data/chunks is absent here, Docker
# creates the mountpoint root:root and the app cannot write chunk images — and
# the failure is silent: ensure_storage_directories() is mkdir(exist_ok=True) on
# a directory that now exists, so startup logs look clean while Levels 0 and 1
# stay permanently blank and only Level 2 works.
RUN useradd -m -u 10001 app \
    && mkdir -p /data/chunks \
    && chown -R app:app /data/chunks
USER app

EXPOSE 8000

# /health returns 503 when the database is unreachable, so this gates
# depends_on: service_healthy for anything downstream. Uses python rather than
# curl because the slim image ships no curl and adding one costs an apt layer.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Ping interval keeps WebSockets alive through proxy idle timeouts (Caddy now,
# an ALB before).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws-ping-interval", "20", "--ws-ping-timeout", "20"]
