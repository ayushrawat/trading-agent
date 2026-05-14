### Stage 1 — build the React frontend ###
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

### Stage 2 — Python backend + bundled frontend ###
FROM python:3.11-slim AS backend
WORKDIR /app

# System deps for some Python wheels (lxml etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/.env.example ./.env.example

# Frontend build output served by FastAPI's StaticFiles.
# main.py looks for backend/static (i.e. /app/static at runtime).
COPY --from=frontend /frontend/dist ./static

# Fly mounts a persistent volume at /data for the SQLite DB.
ENV DATABASE_URL=sqlite:////data/trading_agent.db
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
