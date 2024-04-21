import threading

try:
  import cPickle as pickle
except ImportError:
  import pickle

from cherrypy.lib.sessions import Session
import redis
import cherrypy
from redis import Sentinel

class RedisSession(Session):

    # the default settings
    host = '127.0.0.1'
    port = 6379
    db = 0
    password = None
    tls_skip_verify = False
    is_sentinel = False
    ssl = False
    user = ""


    @classmethod
    def setup(cls, **kwargs):
        """Set up the storage system for redis-based sessions.
        Called once when the built-in tool calls sessions.init.
        """
        # overwritting default settings with the config dictionary values
        for k, v in kwargs.items():
            setattr(cls, k, v)

        if cls.tls_skip_verify:
            cls.ssl_cert_req=None
        else:
            cls.ssl_cert_req="required"

        if cls.is_sentinel:
            sentinel = Sentinel([(cls.host, cls.port)], ssl=cls.ssl, ssl_cert_reqs=cls.ssl_cert_req, sentinel_kwargs={"password":cls.sentinel_pass, "ssl": cls.ssl, "ssl_cert_reqs": cls.ssl_cert_req}, username=cls.user, password=cls.password)
            cls.cache = sentinel.master_for(cls.sentinel_service)
            
        else:
            cls.cache = redis.Redis(
                host=cls.host,
                port=cls.port,
                db=cls.db,
                ssl=cls.ssl,
                username=cls.user,
                password=cls.password)

    def _exists(self):
        return bool(self.cache.exists(self.prefix+self.id))

    def _load(self):
        try:
          return pickle.loads(self.cache.get(self.prefix+self.id))
        except TypeError:
          # if id not defined pickle can't load None and raise TypeError
          return None

    def _save(self, expiration_time):
        pickled_data = pickle.dumps(
            (self._data, expiration_time),
            pickle.HIGHEST_PROTOCOL)

        result = self.cache.setex(self.prefix+self.id, self.timeout * 60, pickled_data)

        if not result:
            raise AssertionError("Session data for id %r not set." % self.prefix+self.id)

    def _delete(self):
        self.cache.delete(self.prefix+self.id)

    # http://docs.cherrypy.org/dev/refman/lib/sessions.html?highlight=session#locking-sessions
    # session id locks as done in RamSession

    locks = {}

    def acquire_lock(self):
        """Acquire an exclusive lock on the currently-loaded session data."""
        self.locked = True
        self.locks.setdefault(self.prefix+self.id, threading.RLock()).acquire()

    def release_lock(self):
        """Release the lock on the currently-loaded session data."""
        self.locks[self.prefix+self.id].release()
        self.locked = False
