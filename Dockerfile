# syntax = docker/dockerfile:1.4.0

FROM ghcr.io/magfest/sideboard:main as build
ARG PLUGINS="[]"
MAINTAINER RAMS Project "code@magfest.org"
LABEL version.rams-core ="0.1"

# install ghostscript and gettext-base
RUN apt-get update && apt-get install -y ghostscript libxml2-dev libxmlsec1-dev dnsutils gettext-base vim jq && rm -rf /var/lib/apt/lists/*

ADD requirements*.txt plugins/uber/
ADD setup.py plugins/uber/
ADD uber/_version.py plugins/uber/uber/

RUN --mount=type=cache,target=/root/.cache /app/env/bin/paver install_deps

ADD uber-wrapper.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/uber-wrapper.sh

RUN <<EOF cat >> PLUGINS.json
$PLUGINS
EOF

RUN jq -r '.[] | "git clone --depth 1 --branch \(.branch|@sh) \(.repo|@sh) \(.path|@sh)"' PLUGINS.json > install_plugins.sh && chmod +x install_plugins.sh && ./install_plugins.sh

ADD . plugins/uber/

FROM build as test
RUN /app/env/bin/pip install mock pytest
CMD /app/env/bin/python3 -m pytest plugins/uber

FROM build as release
ENTRYPOINT ["/usr/local/bin/uber-wrapper.sh"]
CMD ["uber"]