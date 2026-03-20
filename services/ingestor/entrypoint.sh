#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting ingestor..."
exec python -m services.ingestor.main
