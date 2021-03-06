Load testing using [locust.io](http://locust.io).

# Quick Start

## Installing Locust

On your development computer, in the ubersystem repo cloned from github:
```
pip install -r tests/locust/requirements.txt
```

## Running Load Tests

1. Enable the profiler in `INSTALL_DIR/development.ini` on your target server
```
# /srv/reggie/development.ini on staging-web-01-reggie.magfest.org
[cherrypy]
profiling.on = True
```

2. Restart uber on your target server if necessary
```
# on a legacy uber deploy:
sudo supervisorctl restart uber_daemon

# on a newer reggie deploy:
sudo systemctl restart reggie-web
```

3. On your development computer, change to the `tests/locust` directory
(where this `README.md` is):
```
cd tests/locust
```

4. On your development computer, start the locust swarm and point it at the
target server you want to load test
```
locust --host=https://staging-reggie.magfest.org
```

5. Open the locust user interface in your browser and start swarming!
```
http://localhost:8089
```

6. View the results on your target server's profiler:
```
https://staging-reggie.magfest.org/profiler/
```
