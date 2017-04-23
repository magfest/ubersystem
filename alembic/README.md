To autogenerate migrations:
```bash
# Make changes to your models.py file(s) as appropriate
# DO NOT use sep reset_uber_db!
# Keep in mind, relationship "columns" are not real, you do not need migrations
# for them
sep alembic revision --autogenerate -m "Message for revision"
```

Be sure to check your revision and edit it as necessary; auto-generation is not
perfect and may try to drop columns.

To run migrations:
```bash
sep alembic upgrade head
```

To "fast-foward" migrations, i.e., count them as being run without actually
running them:
```bash
sep alembic stamp head
```
