FROM vmearl/sideboard:mff
MAINTAINER RAMS Project "code@magfest.org"
LABEL version.rams-core ="0.1"

# add our code
COPY . plugins/uber/
# go ahead and install base dependencies
RUN /app/env/bin/paver install_deps
