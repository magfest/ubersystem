#!/bin/sh

# This provides simple health checks for use in docker/k8s/etc.
# Pass the task run by this container and it will exit non-zero if something is wrong
# I.e. ./healthcheck.sh uber
set -e

cat <<EOF > celeryconf.py
# celery config used for celery cli-based health checks (Not loaded by ubersystem directly)
broker_url = "${uber_secret_broker_url}"
result_backend = "${uber_secret_broker_url}"
result_backend_transport_options = {
    'global_keyprefix': "${uber_secret_broker_prefix}",
    'global_prefix': "${uber_secret_broker_prefix}"
}
EOF

# If no arguments are passed grab the current CMD from the entrypoint
CMD="${1:-$(cat /proc/1/cmdline | strings -1 | tail -1)}"

if [ "$CMD" = 'uber' ]; then
    curl --fail http://$uber_cherrypy_server_socket_host:$uber_cherrypy_server_socket_port/devtools/health
elif [ "$CMD" = 'celery-beat' ]; then
    # Beat seems to do a good job of dying when things go wrong.
    # If you know a good way to test its health please put it here.
    exit 0
elif [ "$CMD" = 'celery-worker' ]; then
    cd /app
    /usr/local/bin/celery --config celeryconf inspect ping -d celery@$(cat /etc/hostname)
else
    echo "Unknown service"
    exit 1
fi