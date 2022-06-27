from setuptools import setup

exec(open('uber/_version.py').read())
if __name__ == '__main__':
    setup(
        name='uber',
        packages=['uber'],
        version=__version__,
        author='Eli Courtwright and others',
        author_email='code@magfest.org',
        description='The MAGFest Ubersystem - Ticket/Management platform',
        url='https://github.com/magfest/ubersystem',
    )
