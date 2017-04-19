# Running Tests

RAMS plugins require Python 3.4.


## Using tox

The first time tox runs, it may take a few minutes to build its virtual
environment, but each subsequent run should start quickly.

Installing tox:
```
pip install tox
```

To run all tests and pep8 validation from the command line:
```
tox
```

To run pep8 validation only, without running any tests:
```
tox -e pep8
```

To run the tests only, without pep8:
```
tox -e py34
```

To run only the tests in a specific file:
```
tox -e py34 -- -k test_templates.py
```

To run only the tests matching a given substring, like "jinja" for example:
```
tox -e py34 -- -k jinja
```

In general, everything after the `--` is passed as arguments to pytest. For
example, to run the tests with verbose output and without capturing stdout:
```
tox -e py34 -- --verbose --capture=no
```


## Using pytest

Tox is convenient because it creates an isolated test environment with the
correct requirements installed, but the tests can also be run using pytest
directly.

Running the tests using pytest requires a correctly configured development
environment. If you're using the vagrant dev deployment, you probably already
have everything you need.

The tests require settings from both `development-defaults.ini` and
`test-defaults.ini`. The `SIDEBOARD_CONFIG_OVERRIDES` environment variable is
used to specify which config files should be loaded.

To run the tests using pytest:
```
SIDEBOARD_CONFIG_OVERRIDES='development-defaults.ini;test-defaults.ini' pytest uber
```


## Potential pitfalls

You will see errors like the following if the tests are run without loading
`test-defaults.ini`:
```
    def do_execute(self, cursor, statement, parameters, context=None):
>       cursor.execute(statement, parameters)
E       sqlite3.OperationalError: near "DEFERRABLE": syntax error

../../env/lib/python3.4/site-packages/sqlalchemy/engine/default.py:470: OperationalError
```

Make sure `SIDEBOARD_CONFIG_OVERRIDES` is set to
`development-defaults.ini;test-defaults.ini`.

The easiest way to make sure everything is set up correctly is to use tox as
described above. Use tox! Tox is great!
