# Hotel domain-layer tests

Focused tests for the hotel lottery domain modules (`uber.hotel.*` and
`uber.models.hotel`). Deliberately independent of `tests/uber/` and its
conftest — this directory has its own bootstrap.

## Running

From the host, against the running `uber-python` container:

```
docker exec -e DB_CONNECTION_STRING=postgresql://uber_db:uber_db@db:5432/uber_test_hotel \
    uber-python python -m pytest /app/tests/hotel/ -q
```

Notes:

* `DB_CONNECTION_STRING` **must** be set on the pytest process itself:
  `uber.config` reads it at import time. The conftest fails fast with a
  clear message if it points anywhere other than the dedicated
  `uber_test_hotel` database.
* The conftest creates the `uber_test_hotel` database if missing and runs
  the full alembic migration chain on it (idempotent, so re-runs are
  fast). It never touches `uber_db` or `scratch_lottery`.
* Each test runs inside a single transaction on a dedicated session and
  is rolled back at teardown — fixtures flush (so model presave hooks
  run) but never commit.
* Config-dependent assertions read values off `uber.config.c` rather than
  hardcoding them; assertions that need unset config (e.g. the global
  lottery guarantee deadline) `pytest.skip` instead of failing.
