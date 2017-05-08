Load tests using [locust.io](http://locust.io).

# Quick Start

## Installing Locust

On your development computer, if you cloned the ubersystem repo from github:
```
pip install -r tests/locust/requirements.txt
```

If you're using our Vagrant simple deploy, it will look like this:
```
pip install -r ubersystem-deploy/sideboard/plugins/uber/tests/locust/requirements.txt
```

## Running Load Tests

1. Enable the profiler in `sideboard/development.ini` on your target server
```
# sideboard/development.ini on staging4.uber.magfest.org
[cherrypy]
profiling.on = True
```

2. Restart uber on your target server if necessary
```
# on staging4.uber.magfest.org
sudo supervisorctl restart uber_daemon
```

3. On your development computer, change to the `tests/locust` directory
(where this `README.md` is):
```
cd tests/locust
```
Or with our Vagrant simple deploy:
```
cd ubersystem-deploy/sideboard/plugins/uber/tests/locust
```

4. On your development computer, start the locust swarm and point it at the
target server you want to load test:
```
locust --host=https://staging4.uber.magfest.org
```

5. Open the locust user interface in your browser and start swarming!
```
http://localhost:8089
```

6. View the results on your target server's profiler:
```
https://staging4.uber.magfest.org/profiler/
```
