rm -rfv env
python2.7 -m virtualenv --no-site-packages --distribute env

./env/bin/pip install --upgrade distribute
for pydep in mysql-python py-bcrypt pycrypto Django cherrypy nose selenium boto logging_unterpolation requests
do
    ./env/bin/pip install $pydep
done
