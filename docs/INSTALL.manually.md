Manual Installation
==================================

Linux is currently the only supported development platform.  Theoretically this codebase should work on other platforms, but this has not been tested.

This method of installation uses postgres, which is what the actual production server uses, and so should be more supported (but is more complex to set up). A simpler alternate installation method, using sqlite, is at the bottom of this document.

Here's what you need installed before you can run this:
* Python >= 3.3 (with source headers)
* Postgresql 9.0 or later

Let's start by getting all of the Python dependencies installed.  We'll clone the repo, make a virtualenv, install distribute, and then install all of our Python dependencies:

```bash
$ git clone https://github.com/magfest/ubersystem  # or your fork
$ cd magfest
$ python3.3 -m venv env
$ ./env/bin/python setup.py develop
```

Now we need to create a Postgresql database.  The default username, password, and database name is "m13", so we'll go ahead and do that, e.g.

```bash
$ sudo -i
$ sudo -i -u postgres
$ createuser --superuser --pwprompt m13
$ createdb --owner=m13 m13
```

Now we're ready to create all of our database tables, which we can do by running the init_db script.  After that we can actually start the server:

```bash
$ ./env/bin/python uber/init_db.py
$ ./env/bin/python uber/run_server.py
```

Now we can go to http://localhost:4321/ and log in with the email address "magfest@example.com" and the password "magfest".

If you'd live to override any of the default configuration settings, you can create a "development.conf" file in the top-level directory of the repo, and any values you put there will override the default values.  For example, suppose we were running remotely on a cloud server like Rackspace, so instead of binding to localhost, we'd instead bind to our local IP address and tell the web server to issue its redirects appropriately, e.g.

```
hostname = "12.34.56.78"
url_root = "http://12.34.56.78:4321"
```

If you'd like to insert about 10,000 attendees with realistic shifts and whatnot, you can run the following command (warning, this takes 5-10 minutes to insert everything):

```bash
$ ./env/bin/python uber/tests/import_test_data.py
```

Alternatively, you could insert directly with the sql file in the same directory as that script (though you'll need to start with an empty database for this to work), e.g.

```bash
$ psql --host=localhost --username=m13 --password m13 < uber/tests/test_data.sql
```

Alternate Manual Installation - sqlite (quick start)
====================================================

* Install python 3, sqlite, and libcap-dev
* Install (via package manager or `pip3 install --user`): virtualenv, paver
* `git clone https://github.com/magfest/sideboard`
* `cd sideboard`
* `git clone https://github.com/magfest/ubersystem plugins/uber`
    * (the above *must* be a dir named uber, not ubersystem)
* `paver make_venv` (may be at `~/.local/bin/paver`, depending on how you installed it) (Note: paver must use Python3 for this)
* `./env/bin/paver install_deps`
* Init the DB, and create test admin account: `./env/bin/sep reset_uber_db`
* Run it! `./env/bin/python sideboard/run_server.py`
* RAMS is now running on `localhost:8282`!

You now may perform tasks like configuration customization or test data insertion as described above.
