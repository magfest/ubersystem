#!/bin/bash
set -e

# This will replace any variable references in these files
# If you want to add any additional settings here just add
# the variables to the environment when running this.
envsubst < "uber-development.ini.template" > /app/plugins/uber/development.ini
envsubst < "sideboard-development.ini.template" > /app/development.ini

if [ "$1" = 'uber' ]; then
    /app/env/bin/python3 /app/sideboard/sep.py alembic upgrade heads
    /app/env/bin/python3 /app/sideboard/run_server.py
elif [ "$1" = 'celery-beat' ]; then
    /app/env/bin/celery -A uber.tasks beat --pidfile=
elif [ "$1" = 'celery-worker' ]; then
    /app/env/bin/celery -A uber.tasks worker
fi

exec "$@"