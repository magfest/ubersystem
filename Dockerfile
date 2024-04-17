# syntax = docker/dockerfile:1.4.0

FROM python:3.12.3-slim as build
WORKDIR /app
ENV PYTHONPATH=/app

ARG PLUGINS="[]"

# install ghostscript and gettext-base
RUN --mount=type=cache,target=/var/lib/apt/lists \
    --mount=type=cache,target=/var/cache/apt \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y ghostscript libxml2-dev libxmlsec1-dev dnsutils gettext-base postgresql-client libpq-dev vim jq git

ADD requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache \
    pip install -r requirements.txt

ADD uber-wrapper.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/uber-wrapper.sh

FROM build as test
RUN pip install -r requirements_test.txt
CMD python -m pytest
ADD . /app

FROM build as release
ENTRYPOINT ["/usr/local/bin/uber-wrapper.sh"]
CMD ["uber"]
ADD . /app