FROM ghcr.io/magfest/sideboard:main
MAINTAINER RAMS Project "code@magfest.org"
LABEL version.rams-core ="0.1"

# install ghostscript and gettext-base
RUN apt-get update && apt-get install -y ghostscript gettext-base vim && rm -rf /var/lib/apt/lists/*

ADD requirements*.txt plugins/uber/

RUN /app/env/bin/paver install_deps
RUN /app/env/bin/python3 -m pip install SQLAlchemy==1.3.0

ADD . plugins/uber/

ADD uber-development.ini.template ./uber-development.ini.template
ADD sideboard-development.ini.template ./sideboard-development.ini.template
ADD uber-wrapper.sh /usr/local/bin/

ENV HOST=0.0.0.0
ENV PORT=8282
ENV DEFAULT_URL=/uber
ENV DEBUG=false
ENV SESSION_HOST=redis
ENV SESSION_PORT=6379
ENV BROKER_HOST=rabbitmq
ENV BROKER_PORT=5672
ENV BROKER_USER=celery
ENV BROKER_PASS=celery
ENV BROKER_VHOST=uber

ENTRYPOINT ["uber-wrapper.sh"]
CMD ["uber"]
