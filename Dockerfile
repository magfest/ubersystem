# syntax = docker/dockerfile:1.4.0

FROM python:3.12.3-alpine as build
ARG PLUGINS="[]"
ARG PLUGIN_NAMES="[]"
WORKDIR /app
ENV PYTHONPATH=/app
ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/root/.cargo/bin

ADD https://astral.sh/uv/install.sh /tmp/install-uv.sh

# We're upgrading to edge because lxml comes with its own libxml2 which must match the system version for xmlsec to work
# We can remove this once python ships a docker container with a libxml2 that matches lxml
# Check lxml version with:
# import lxml.etree
# lxml.etree.LIBXML_VERSION
# Alternatively, build lxml from source to link against system libxml2: RUN uv pip install --system --no-binary lxml lxml
RUN --mount=type=cache,target=/var/cache/apk \
    sed -i 's/v3.19/edge/' /etc/apk/repositories && \
    apk --update-cache upgrade && \
    apk add git libxml2 xmlsec-dev build-base jq curl && \
    sh /tmp/install-uv.sh && source $HOME/.local/bin/env \
    rm /tmp/install-uv.sh

ADD requirements.txt /app/
#RUN --mount=type=cache,target=/root/.cache \
RUN /usr/uv pip install --system -r requirements.txt;

ADD uber-wrapper.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/uber-wrapper.sh

RUN <<EOF cat >> PLUGINS.json
$PLUGINS
EOF

RUN jq -r '.[] | "git clone --depth 1 --branch \(.branch|@sh) \(.repo|@sh) \(.path|@sh)"' PLUGINS.json > install_plugins.sh && chmod +x install_plugins.sh && ./install_plugins.sh
ENV uber_plugins=$PLUGIN_NAMES

FROM build as test
ADD requirements_test.txt /app/
#RUN --mount=type=cache,target=/root/.cache \
RUN /usr/uv pip install --system -r requirements_test.txt
CMD python -m pytest
ADD . /app

FROM build as release
ENTRYPOINT ["/usr/local/bin/uber-wrapper.sh"]
CMD ["uber"]
ADD . /app
