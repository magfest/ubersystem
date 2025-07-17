from __future__ import unicode_literals
import psutil
process = psutil.Process()
print(f"Entrypoint {process.memory_info().rss}")
print(f"unicode {process.memory_info().rss}")
import cherrypy
print(f"cherrypy {process.memory_info().rss}")

import uber.server
print(f"Uber {process.memory_info().rss}")
if __name__ == '__main__':
    cherrypy.engine.start()
    print(f"Engine started {process.memory_info().rss}")
    try:
        cherrypy.engine.block()
    finally:
        print(f"Finally {process.memory_info().rss}")
