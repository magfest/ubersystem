#!/bin/bash
set -e

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8282}"
export DEFAULT_URL="${DEFAULT_URL:-/}"
export DEBUG="${DEBUG:-false}"
export SESSION_HOST="${SESSION_HOST:-redis}"
export SESSION_PORT="${SESSION_PORT:-6379}"
export BROKER_HOST="${BROKER_HOST:-rabbitmq}"
export BROKER_PORT="${BROKER_PORT:-5672}"
export BROKER_USER="${BROKER_USER:-celery}"
export BROKER_PASS="${BROKER_PASS:-celery}"
export BROKER_VHOST="${BROKER_VHOST:-uber}"

envsubst < "uber-development.ini.template" > /app/plugins/uber/development.ini
echo "Running with uber config as follows:"
cat /app/plugins/uber/development.ini
envsubst < "sideboard-development.ini.template" > /app/development.ini
echo "Running with sideboard config as follows:"
cat /app/development.ini

if [ "$1" = 'uber' ]; then
    /app/env/bin/python3 /app/sideboard/sep.py alembic upgrade heads
    /app/env/bin/python3 /app/sideboard/run_server.py
elif [ "$1" = 'celery-beat' ]; then
    /app/env/bin/celery -A uber.tasks beat --pidfile=
elif [ "$1" = 'celery-worker' ]; then
    /app/env/bin/celery -A uber.tasks worker
fi

exec "$@"