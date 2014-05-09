#!/bin/bash


################################################################################
# OS dependencies
################################################################################

sudo apt-get update -y
sudo apt-get install -y python3-dev postgresql postgresql-contrib libpq-dev language-pack-id git
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


################################################################################
# Set up our virtualenv
################################################################################

cd /home/vagrant/magfest
if [ -f .env-success ]; then
    echo "Virtualenv already exists"
else
    rm -rf env/
    python3 -m venv env
    ./env/bin/python distribute_setup.py
    ./env/bin/python setup.py develop
    cp vagrant/bash_aliases /home/vagrant/.bash_aliases
    rm -f distribute*.tar.gz
    touch .env-success
fi

echo "MAGFest Vagrant VM successfully provisioned"
