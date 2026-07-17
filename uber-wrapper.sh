#!/bin/sh
set -e

if [ -n "${CONFIG_REPO}" ]; then
    echo "Loading configuration from git repo ${CONFIG_REPO}"
    python /app/make_config.py --repo "${CONFIG_REPO}" --environment config.env --paths ${CONFIG_PATHS}
    source config.env
fi

if [ "$1" = 'uber' ]; then
    echo "If this is the first time starting this server go to the following URL to create an account:"
    echo "http://localhost/accounts/insert_test_admin"
    echo "From there the default login is magfest@example.com / magfest"
    python /app/sep.py alembic upgrade heads
    # Auto-scale worker processes to container cgroups CPU quota (os.process_cpu_count)
    # or fall back to explicit GRANIAN_WORKERS environment variable override.
    WORKERS="${GRANIAN_WORKERS:-$(python -c 'import os; print(getattr(os, "process_cpu_count", os.cpu_count)() or 1)')}"
    exec granian --interface wsgi --host 0.0.0.0 --port 80 --workers "${WORKERS}" --threads "${GRANIAN_THREADS:-2}" run_server:application
elif [ "$1" = 'celery-beat' ]; then
    celery -A uber.tasks beat --loglevel=DEBUG --pidfile=
elif [ "$1" = 'celery-worker' ]; then
    celery -A uber.tasks worker --loglevel=DEBUG
else
    exec "$@"
fi
