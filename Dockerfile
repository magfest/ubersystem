# syntax = docker/dockerfile:1.4.0

FROM ghcr.io/magfest/sideboard:old_python
ARG PLUGINS="[]"
MAINTAINER RAMS Project "code@magfest.org"
LABEL version.rams-core ="0.1"

# install ghostscript and gettext-base
RUN apt-get update && apt-get install -y ghostscript libxml2-dev libxmlsec1-dev dnsutils gettext-base vim jq && rm -rf /var/lib/apt/lists/*

ADD requirements*.txt plugins/uber/
ADD setup.py plugins/uber/
ADD uber/_version.py plugins/uber/uber/

RUN /app/env/bin/paver install_deps

ADD uber-development.ini.template ./uber-development.ini.template
ADD sideboard-development.ini.template ./sideboard-development.ini.template
ADD uber-wrapper.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/uber-wrapper.sh
ADD rebuild-config.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/rebuild-config.sh

RUN <<EOF cat >> PLUGINS.json
$PLUGINS
EOF

RUN jq -r '.[] | "git clone --depth 1 --branch \(.branch|@sh) \(.repo|@sh) \(.path|@sh)"' PLUGINS.json > install_plugins.sh && chmod +x install_plugins.sh && ./install_plugins.sh

ADD . plugins/uber/

# These are just semi-reasonable defaults. Use either -e or --env-file to set what you need
# I.e.:
# docker run -it -e HOST=192.168.0.10 -e PORT=80 ghcr.io/magfest/ubersystem:main
# or
# echo "HOST=192.168.0.10" > uberenv
# docker run -it --env-file uberenv ghcr.io/magfest/ubersystem:main
ENV HOST=0.0.0.0
ENV PORT=8282
ENV HOSTNAME=localhost
ENV DEFAULT_URL=
ENV DEBUG=false
ENV SESSION_HOST=redis
ENV SESSION_PORT=6379
ENV REDIS_HOST=redis
ENV REDIS_PORT=6379
ENV SESSION_PREFIX=uber
ENV BROKER_PROTOCOL=amqp
ENV BROKER_HOST=rabbitmq
ENV BROKER_PORT=5672
ENV BROKER_USER=celery
ENV BROKER_PASS=celery
ENV BROKER_VHOST=uber
ENV BROKER_PREFIX=uber

ENTRYPOINT ["/usr/local/bin/uber-wrapper.sh"]
CMD ["uber"]
