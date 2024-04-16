#!/bin/bash
set -e

if [ -n "${CONFIG_REPO}" ]; then
    echo "Loading configuration from git repo ${CONFIG_REPO}"
    /app/env/bin/python /app/plugins/uber/make_config.py --repo "${CONFIG_REPO}" --environment config.env --paths ${CONFIG_PATHS}
    source config.env
fi

if [ "$1" = 'uber' ]; then
    echo "If this is the first time starting this server go to the following URL to create an account:"
    echo "http://localhost/accounts/insert_test_admin"
    echo "From there the default login is magfest@example.com / magfest"
    /app/env/bin/python3 /app/sideboard/sep.py alembic upgrade heads
    /app/env/bin/python3 /app/sideboard/run_server.py
elif [ "$1" = 'celery-beat' ]; then
    /app/env/bin/celery -A uber.tasks beat --loglevel=DEBUG --pidfile=
elif [ "$1" = 'celery-worker' ]; then
    /app/env/bin/celery -A uber.tasks worker --loglevel=DEBUG
else
    exec "$@"
fi
