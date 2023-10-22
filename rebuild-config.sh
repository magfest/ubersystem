#!/bin/bash
set -e

# This will replace any variable references in these files
# If you want to add any additional settings here just add
# the variables to the environment when running this.
envsubst < "uber-development.ini.template" > /app/plugins/uber/development.ini
envsubst < "sideboard-development.ini.template" > /app/development.ini

if [ "$1" = 'git' ]; then
/app/env/bin/python /app/plugins/uber/make_config.py --repo https://github.com/magfest/terraform-aws-magfest.git --paths uber_config/environments/dev uber_config/events/$2 uber_config/events/$2/$3
fi