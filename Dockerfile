# syntax = docker/dockerfile:1.4.0

FROM ghcr.io/magfest/sideboard:main as build
ENV PYTHONPATH=${PYTHONPATH}:/app/plugins/uber
ARG PLUGINS="[]"
LABEL version.rams-core ="0.1"

# install ghostscript and gettext-base
RUN --mount=type=cache,target=/var/lib/apt/lists \
    --mount=type=cache,target=/var/cache/apt \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y ghostscript libxml2-dev libxmlsec1-dev dnsutils gettext-base postgresql-client vim jq

ADD requirements.txt /app/plugins/uber/
RUN --mount=type=cache,target=/root/.cache \
    pip install -r /app/plugins/uber/requirements.txt

ADD uber-wrapper.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/uber-wrapper.sh

RUN <<EOF cat >> PLUGINS.json
$PLUGINS
EOF

RUN jq -r '.[] | "git clone --depth 1 --branch \(.branch|@sh) \(.repo|@sh) \(.path|@sh)"' PLUGINS.json > install_plugins.sh && chmod +x install_plugins.sh && ./install_plugins.sh

FROM build as test
RUN pip install -r requirements_test.txt
CMD python -m pytest plugins/uber
ADD . plugins/uber/

FROM build as release
ENTRYPOINT ["/usr/local/bin/uber-wrapper.sh"]
CMD ["uber"]
ADD . plugins/uber/