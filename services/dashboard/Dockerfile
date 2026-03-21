FROM node:22-slim AS frontend

WORKDIR /web
COPY services/dashboard/web/package.json services/dashboard/web/package-lock.json* ./
RUN npm install
COPY services/dashboard/web/ .
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY services/dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
COPY services/__init__.py /app/services/
COPY services/dashboard/__init__.py /app/services/dashboard/
COPY services/dashboard/api/ /app/services/dashboard/api/

# Copy built React app
COPY --from=frontend /web/dist /app/services/dashboard/web/dist

ENV PYTHONPATH=/app

CMD ["bash", "-c", "alembic upgrade head && uvicorn services.dashboard.api.main:app --host 0.0.0.0 --port 8080"]
