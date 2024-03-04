# Running Tests

Sideboard plugins require Python 3.4.


## Using tox

The first time tox runs, it may take a few minutes to build its virtual
environment at the `installdeps` step. Each subsequent run should start quickly.

1. Install tox if it's not already installed:
    ```
    pip install tox
    ```

2. Navigate to the plugin whose tests you want to run. You should be in the same
directory as the `tox.ini` file -- this should always be the root folder of
the plugin. E.g.:
    ```
    cd reggie-formula/reggie_install/plugins/my_plugin
    ```

3. Run your tests! To run all tests and flake8 validation from the command line:
    ```
    tox
    ```

    1. To run flake8 validation only, without running any tests:
        ```
        tox -e flake8
        ```

    2. To run the tests only, without flake8:
        ```
        tox -e py36
        ```

    3. To run only the tests in a specific file:
        ```
        tox -e py36 -- -k test_templates.py
        ```

    4. To run only the tests matching a given substring, like "jinja" for example:
        ```
        tox -e py36 -- -k jinja
        ```

4. In general, everything after the `--` is passed as arguments to pytest. For
example, to run the tests with verbose output and without capturing stdout:
    ```
    tox -e py36 -- --verbose --capture=no
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


## Troubleshooting
### No test-defaults.ini
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

### Tox using old code
In some cases, you may see errors that look like you have old code even though you're on the latest master.
For example, tox may report being unable to import a module recently added to Sideboard. In these cases, tox's
environment needs to be refreshed by add the `-r` flag to a command. Try running `tox -r`!

The easiest way to make sure everything is set up correctly is to use tox as
described above. Use tox! Tox is great!
