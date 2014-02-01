from setuptools import setup

if __name__ == '__main__':
    setup(
        name='uber',
        version='13.0',
        packages=['uber'],
        author='Eli Courtwright',
        author_email='eli@courtwright.org',
        description='The MAGFest Ubersystem',
        url='https://github.com/EliAndrewC/magfest',
        install_requires=open('requirements.txt').readlines()
    )
