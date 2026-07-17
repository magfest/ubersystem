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
    # Auto-scale worker processes with CPU cores (cgroups quota), capped at 4 by default
    # for multi-core GIL parallelism while maintaining bounded memory with gc.freeze().
    export GRANIAN=true
    DEFAULT_WORKERS="$(python -c 'import os; c = getattr(os, "process_cpu_count", os.cpu_count)() or 1; print(min(c, 4))')"
    WORKERS="${GRANIAN_WORKERS:-${DEFAULT_WORKERS}}"
    BLOCKING_THREADS="${GRANIAN_BLOCKING_THREADS:-${GRANIAN_THREADS:-4}}"
    exec granian --interface wsgi --host 0.0.0.0 --port 80 --workers "${WORKERS}" --blocking-threads "${BLOCKING_THREADS}" run_server:application
elif [ "$1" = 'celery-beat' ]; then
    celery -A uber.tasks beat --loglevel=DEBUG --pidfile=
elif [ "$1" = 'celery-worker' ]; then
    celery -A uber.tasks worker --loglevel=DEBUG
else
    exec "$@"
fi
