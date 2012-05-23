rm -rfv env
python2.7 -m virtualenv --no-site-packages env

for pydep in mysql-python py-bcrypt pycrypto Django cherrypy nose selenium boto logging_unterpolation requests
do
    ./env/bin/easy_install $pydep
done
