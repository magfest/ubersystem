#!/bin/bash

# This provides simple health checks for use in docker/k8s/etc.
# Pass the task run by this container and it will exit non-zero if something is wrong
# I.e. ./healthcheck.sh uber
set -e

# If no arguments are passed grab the current CMD from the entrypoint
CMD="${1:-$(cat /proc/1/cmdline | strings -1 | tail -1)}"

if [ "$CMD" = 'uber' ]; then
    curl --fail http://$HOST:$PORT/uber/devtools/health
elif [ "$CMD" = 'celery-beat' ]; then
    # Beat seems to do a good job of dying when things go wrong.
    # If you know a good way to test its health please put it here.
    exit 0
elif [ "$CMD" = 'celery-worker' ]; then
    cd /app
    /app/env/bin/celery --config celeryconf inspect ping -d celery@$(cat /etc/hostname)
fi