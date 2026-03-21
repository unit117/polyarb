#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting optimizer..."
exec python -m services.optimizer.main
