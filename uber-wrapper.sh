#!/bin/bash
set -e

# SESSION_HOST and BROKER_HOST may point to SRV records that need to get resolved to a host/port
SESSION_REC=$(dig srv +noall +answer +short "$SESSION_HOST" | cut -d ' ' -f 3,4 | head -1)
BROKER_REC=$(dig srv +noall +answer +short "$BROKER_HOST" | cut -d ' ' -f 3,4 | head -1)
if [[ ! -z "$SESSION_REC" ]]; then
    SESSION_HOST=$(echo $SESSION_REC | cut -d ' ' -f 2)
    SESSION_PORT=$(echo $SESSION_REC | cut -d ' ' -f 1)
fi
if [[ ! -z "$BROKER_REC" ]]; then
    BROKER_HOST=$(echo $BROKER_REC | cut -d ' ' -f 2)
    BROKER_PORT=$(echo $BROKER_REC | cut -d ' ' -f 1)
fi

# This will replace any variable references in these files
# If you want to add any additional settings here just add
# the variables to the environment when running this.
envsubst < "uber-development.ini.template" > /app/plugins/uber/development.ini
envsubst < "sideboard-development.ini.template" > /app/development.ini

if [ -n "${UBERSYSTEM_GIT_CONFIG}" ]; then
    echo "Loading UBERSYSTEM_CONFIG from git repo ${UBERSYSTEM_GIT_CONFIG}"
    /app/env/bin/python /app/plugins/uber/make_config.py --repo "${UBERSYSTEM_GIT_CONFIG}" --paths ${UBERSYSTEM_GIT_CONFIG_PATHS}
fi

if [ -n "${UBERSYSTEM_CONFIG}" ]; then
    echo "Parsing config from environment"
    /app/env/bin/python /app/plugins/uber/make_config.py
fi

if [ "$1" = 'uber' ]; then
    echo "If this is the first time starting this server go to the following URL to create an account:"
    echo "http://${HOSTNAME}:${PORT}${DEFAULT_URL}/accounts/insert_test_admin"
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
