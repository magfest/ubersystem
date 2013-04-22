rm -rfv env
python3.3 -m venv env
source ./env/bin/activate
python distribute_setup.py

for pydep in Django psycopg2 py3k-bcrypt logging_unterpolation requests nose readline
do
    ./env/bin/easy_install $pydep
done

# need to install CherryPy and Stripe from development
