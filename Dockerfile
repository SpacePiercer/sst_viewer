# sst_viewer, data/CSV/GIF only. No R, Quarto or TeX: PDF rendering stays a
# local-PC activity, which keeps this image around 700 MB instead of ~3 GB.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runs as a non-root user; the writable state (library/, cache/, users.json,
# secret.key, areas.json) arrives as volumes owned by this uid.
RUN useradd --create-home --uid 10001 sst
COPY --chown=sst:sst . .
USER sst

EXPOSE 8000
# --proxy-headers so the client IP the login throttle keys on is the real one
# from Caddy's X-Forwarded-For, not the proxy's own address. Trusting those
# headers is only safe because nothing but Caddy can reach this port.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
