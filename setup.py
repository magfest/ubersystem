from setuptools import setup

exec(open('uber/_version.py').read())
if __name__ == '__main__':
    setup(
        name='uber',
        packages=['uber'],
        version=__version__,
        author='Eli Courtwright',
        author_email='eli@courtwright.org',
        description='The MAGFest Ubersystem',
        url='https://github.com/magfest/ubersystem',
        install_requires=open('requirements.txt').readlines()
    )
