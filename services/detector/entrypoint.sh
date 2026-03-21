#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting detector..."
exec python -m services.detector.main
