FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + the prebuilt, read-only data (AniList JSON + Chroma index).
# The index is baked in, so the container needs no ingestion/embedding at boot.
COPY app ./app
COPY data/anime.json ./data/anime.json
COPY data/chroma ./data/chroma

# Hosts (Render/Railway/Fly) inject $PORT; default to 8000 locally.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
