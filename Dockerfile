# syntax = docker/dockerfile:1.4.0

FROM python:3.13-alpine AS build
ARG PLUGINS="[]"
ARG PLUGIN_NAMES="[]"
ARG LXML="6.0.0"
WORKDIR /app
ENV PYTHONPATH=/app
ENV PATH=/root/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
ENV DEBIAN_FRONTEND=noninteractive

ADD https://astral.sh/uv/install.sh /tmp/install-uv.sh
RUN sh /tmp/install-uv.sh && rm /tmp/install-uv.sh

# We're upgrading to edge because lxml comes with its own libxml2 which must match the system version for xmlsec to work
# We can remove this once python ships a docker container with a libxml2 that matches lxml
# Check lxml version with:
# import lxml.etree
# lxml.etree.LIBXML_VERSION
# Alternatively, build lxml from source to link against system libxml2: RUN uv pip install --system --no-binary lxml lxml
RUN --mount=type=cache,target=/var/cache/apk \
    apk --update-cache upgrade && \
    apk add git libxml2 xmlsec-dev build-base jq curl openssh

RUN uv pip install --system https://github.com/magfest/lxml/releases/download/v$LXML/lxml-$LXML-cp313-cp313-musllinux_1_2_$(uname -m).whl

ADD requirements.txt /app/
RUN uv pip install --system -r requirements.txt

COPY --chmod=755 uber-wrapper.sh /usr/local/bin/

RUN <<EOF cat >> PLUGINS.json
$PLUGINS
EOF

RUN jq -r '.[] | "git clone --depth 1 --branch \(.branch|@sh) \(.repo|@sh) \(.path|@sh)"' PLUGINS.json > install_plugins.sh && \
    chmod +x install_plugins.sh && \
    ./install_plugins.sh
ENV uber_plugins=$PLUGIN_NAMES

FROM build AS test
ADD requirements_test.txt /app/
RUN uv pip install --system -r requirements_test.txt
ADD . /app
CMD ["python3", "-m", "pytest", "-s", "/app/tests/integration/performance.py"]


FROM build AS release
ADD . /app
ENTRYPOINT ["/usr/local/bin/uber-wrapper.sh"]
CMD ["uber"]