#!/bin/bash

# must NOT be python 3, splinter wont support it
PYTHON_VER=python2.7

rm -rf env

virtualenv env -p $PYTHON_VER

. env/bin/activate

pip install selenium splinter boto
