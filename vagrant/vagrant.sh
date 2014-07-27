#!/bin/bash


################################################################################
# OS dependencies
################################################################################

sudo apt-get update -y
sudo apt-get install -y python3-dev postgresql postgresql-contrib libpq-dev language-pack-id git lynx tofrodos
sudo locale-gen en_US en_US.UTF-8 hu_HU hu_HU.UTF-8
sudo dpkg-reconfigure locales


################################################################################
# Postgres configuration
################################################################################

sudo service postgresql start

if [[ `sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='m13'"` == "1" ]]; then
    echo "User already exists"
else
    echo "CREATE USER m13 WITH PASSWORD 'm13' SUPERUSER;" | sudo -u postgres psql
fi

if [[ `sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='m13'"` == "1" ]]; then
    echo "Database already exists"
else
    sudo -u postgres createdb --owner=m13 m13
    cat /home/vagrant/magfest/uber/tests/test_data.sql | sudo -u postgres psql m13
fi

# there is a bug in python -m venv which doesnt obey --copies (i.e. don't do any symlinks)
# I have submitted this to CPython for inclusion but for now, patch the installed python file.
# (we can't use symlinks with SMB shares)
sudo patch /usr/lib/python3.4/venv/__init__.py < /home/vagrant/magfest/vagrant/venv-symlink-fix.patch


################################################################################
# Check out Sideboard
################################################################################

cd /home/vagrant
if [ -d /home/vagrant/sideboard ]; then
    echo "Sideboard already cloned"
else
    git clone https://github.com/appliedsec/sideboard
    ln -s /home/vagrant/magfest /home/vagrant/sideboard/plugins/uber
fi

################################################################################
# Set up the Sideboard virtualenv and install our dependencies
################################################################################

cd /home/vagrant/sideboard
if [ -f .env-success ]; then
    echo "Virtualenv already exists"
else
    rm -rf env/
    python3 -m venv env --without-pip --copies
    chmod 755 ./env/bin/python  # not sure why this stopped being executable by default
    cp ../magfest/distribute_setup.py .
    ./env/bin/python distribute_setup.py
    ./env/bin/python setup.py develop
    ./env/bin/paver install_deps
    ./env/bin/sep reset_uber_db
    cp /home/vagrant/magfest/vagrant/bash_aliases /home/vagrant/.bash_aliases
    rm -f distribute*.tar.gz
    touch .env-success
fi

chown -R vagrant.vagrant /home/vagrant/sideboard
chmod 755 /home/vagrant/sideboard/env/bin/python  # not sure why this isn't executable by default

echo "MAGFest Vagrant VM successfully provisioned"
