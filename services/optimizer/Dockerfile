FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY services/optimizer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
COPY services/__init__.py /app/services/
COPY services/optimizer/ /app/services/optimizer/

ENV PYTHONPATH=/app

CMD ["bash", "services/optimizer/entrypoint.sh"]
