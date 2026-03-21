FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Combine requirements from all services the backtester touches
COPY services/simulator/requirements.txt /tmp/sim.txt
COPY services/optimizer/requirements.txt /tmp/opt.txt
COPY services/detector/requirements.txt  /tmp/det.txt
COPY services/ingestor/requirements.txt  /tmp/ing.txt

RUN cat /tmp/sim.txt /tmp/opt.txt /tmp/det.txt /tmp/ing.txt | \
    sort -u > /tmp/all.txt && \
    pip install --no-cache-dir -r /tmp/all.txt

COPY shared/           /app/shared/
COPY alembic/          /app/alembic/
COPY alembic.ini       /app/
COPY services/__init__.py /app/services/
COPY services/simulator/  /app/services/simulator/
COPY services/optimizer/  /app/services/optimizer/
COPY services/detector/   /app/services/detector/
COPY services/ingestor/   /app/services/ingestor/
COPY scripts/             /app/scripts/

ENV PYTHONPATH=/app

CMD ["python", "-m", "scripts.backtest"]
