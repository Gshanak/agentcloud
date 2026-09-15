# agentcloud standalone server — Hugging Face Spaces (free CPU, no card).
# HF Spaces requires the app to listen on port 7860.

FROM python:3.12-slim

# HF Spaces runs containers as a non-root user (UID 1000).
RUN useradd -m -u 1000 user

WORKDIR /app

# Install dependencies first for layer caching.
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# The server code + the shared overlay (pure helpers, AutoGen team factory).
COPY server/ ./server/
COPY platform_overlay/ ./platform_overlay/

# The two PWAs, served as static apps under /news and /stories.
COPY apps/news-curator-pwa/ ./static/news/
COPY apps/storyteller-pwa/ ./static/stories/

# platform_overlay on PYTHONPATH so `backend.blocks.*` imports resolve,
# exactly like the platform deployment and the test suite.
ENV PYTHONPATH=/app/platform_overlay \
    STATIC_DIR=/app/static

RUN chown -R user:user /app
USER user

EXPOSE 7860

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "7860"]
