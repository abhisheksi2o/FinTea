# Multi-stage build: frontend (Vite) + backend (FastAPI) with LibreOffice for formula verification
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-calc fonts-liberation && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY --from=web /web/dist ./frontend/dist
ENV FINTEA_FRONTEND_DIST=/app/frontend/dist
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "fintea.main:app", "--host", "0.0.0.0", "--port", "8000"]
