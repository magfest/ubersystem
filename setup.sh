rm -rfv env
python3.3 -m venv env
source ./env/bin/activate

# distribute doesn't come with venv, need to copy over distribute_setup.py
# MySQL needs to use the special github version for Python 3
# Django 1.5 isn't out yet
# boto needs the neo branch in the github repo

for pydep in py3k-bcrypt nose selenium logging_unterpolation requests
do
    ./env/bin/easy_install $pydep
done
