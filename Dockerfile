# syntax = docker/dockerfile:1.4.0

FROM python:3.14-slim AS build
ARG PLUGINS="[]"
ARG PLUGIN_NAMES="[]"
ARG LXML="6.1.1"
WORKDIR /app
ENV PYTHONPATH=/app
ENV PATH=/root/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
ENV DEBIAN_FRONTEND=noninteractive

# Install uv directly from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies required for ortools, xmlsec, lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libxml2 \
    libxml2-dev \
    libxslt1-dev \
    libxmlsec1-dev \
    pkg-config \
    build-essential \
    jq \
    curl \
    openssh-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Build lxml from source to ensure it links against the system libxml2 
# so that it is compatible with xmlsec.
RUN uv pip install --system --no-binary lxml lxml==$LXML

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
CMD ["python3", "-m", "pytest"]

FROM build AS release
ADD . /app
ENTRYPOINT ["/usr/local/bin/uber-wrapper.sh"]
CMD ["uber"]