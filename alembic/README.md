# Autogenerating Migrations

Assuming you're working on a plugin named myplugin:

1. Add Tables and Columns to `myplugin/myplugin/models.py`, and program as you
normally do.
2. When you're ready to commit your new model changes run the following
commands:
```
sep drop_uber_db
sep alembic upgrade head
sep alembic --plugin myplugin revision --autogenerate -m "Migration description"
sep alembic upgrade head
```
3. Though it is unusual, alembic will sometimes miss `ALTER` statements when
the initial migration is created. To make sure alembic recognizes every change
to the database, try generating new revisions again:
```
sep alembic --plugin myplugin revision --autogenerate -m "Additional alter statements"
sep alembic upgrade head
```
4. Verify the new migrations manually by inspecting the generated revision
scripts and editing them as necessary; auto-generation is not perfect and may
try to unnecessarily drop and re-add columns. Keep in mind, relationship
"columns" are not real, you do not need migrations for them.
5. Additionally, you can also verify the new migrations by running a
comparison of the migration and the results of `sep reset_uber_db`:
```
pg_dump -s mydbname > alembic.sql
sep reset_uber_db
pg_dump -s mydbname > reset_uber_db.sql
diff alembic.sql reset_uber_db.sql
```
The unit tests already do this automatically, which is why this step is
optional. Keep in mind, even if the resulting schemas are identical, alembic
could internally be dropping and re-adding columns or tables resulting in
catastrophic data loss. That is why manual inspection is always recommended.

# `sep alembic` Command

`sep alembic` is a frontend for the alembic script with additional uber
specific facilities.

`sep alembic` supports all the same arguments as the regular `alembic`
command, with the addition of the `--plugin PLUGIN_NAME` option.

Passing `--plugin PLUGIN_NAME` will choose the correct alembic version path
for the given plugin. If `--plugin` is omitted, it will default to `uber`.

If `--version-path PATH` is also specified, it will override the version
path chosen for the plugin. This functionality is rarely needed, and best
left unused.

If a new migration revision is created for a plugin that previously did
not have any revisions, then a new branch label is applied using the
plugin name. For example:

    sep alembic --plugin myplugin revision --autogenerate -m "Initial migration"

A new revision script will be created in `myplugin/alembic/versions/`
with a branch label of "myplugin". The `myplugin/alembic/versions/`
directory will be created if it does not already exist.


# Uber's Alembic Branches

Uber's alembic branches mirror the dependency structure of the plugins
themselves:
```
(uber)-+->[uber@head]
       |
       +-(panels)-+->[panels@head]
       |          |
       |          +-(bands)->[bands@head]
       |          |
       |          +-(tabletop)->[tabletop@head]
       |
       +-(attendee_tournaments)->[attendee_tournaments@head]
       |
       +-(hotel)->[hotel@head]
       |
       +-(magprime)->[magprime@head]
       |
       +-(magstock)->[magstock@head]
       |
       +-(mivs)->[mivs@head]
```

When adding revisions with `sep alembic --plugin NAME revision --autogenerate`,
care must be taken to make sure that the correct plugin is chosen for the
updated models. If you've made changes in `panels/models.py` you must specify
the panels plugin like so: `sep alembic --plugin panels`.

If you specify the wrong plugin then the migrations will be added to the
wrong repository. This isn't the end of the world – the tests will fail and
you'll have to revert your changes in GitHub, but that's the worst that will
happen.