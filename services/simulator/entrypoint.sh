#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting simulator..."
exec python -m services.simulator.main
