from setuptools import setup

if __name__ == '__main__':
    setup(
        name='uber',
        version='13.0',
        packages=['uber'],
        author='Eli Courtwright',
        author_email='eli@courtwright.org',
        description='The MAGFest Ubersystem',
        url='https://bitbucket.org/EliAndrewC/magfest',
        install_requires = [
            "Django==1.6.1",
            "psycopg2==2.5.2",
            "py3k-bcrypt==0.3",
            "logging_unterpolation==0.2.0",
            "stripe==1.11.0",
            "CherryPy==3.2.4",
        ]
    )
