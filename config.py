from common import *

TEST_DB, TEST_USER, TEST_PASS = ["magtest"] * 3

if sys.argv[0].endswith("nosetests") or "TESTING" in os.environ:
    PORT = 1234
    AUTORELOAD = False
    DBUSER, DBPASS, DBNAME = TEST_DB, TEST_USER, TEST_PASS
else:
    PORT = 4321
    AUTORELOAD = True
    DBUSER, DBPASS, DBNAME = ["m12"] * 3

if DEV_BOX:
    state.HOSTNAME = "localhost:{}".format(PORT)
    STRIPE_SECRET_KEY = "sk_test_CvvvyHs2XnU9giMYDCUnIpF4"
    STRIPE_PUBLIC_KEY = "pk_test_t36jT3di98A0rnENDejBE1Vg"

cherrypy.config.update({
    "engine.autoreload.on": AUTORELOAD,
    
    "server.socket_host": "0.0.0.0",
    "server.socket_port": PORT,
    "server.protocol_version": "HTTP/1.0",
    
    "log.screen": False,
    "checker.check_skipped_app_config": False,
    
    "tools.sessions.on": True,
    "tools.sessions.path": state.PATH,
    "tools.sessions.storage_type": "file",
    "tools.sessions.storage_path": "sessions",
    "tools.sessions.timeout": 60 * 24 * 365
})

django.conf.settings.configure(
    TEMPLATE_DEBUG = True,
    TEMPLATE_DIRS  = ["templates","static"],
    DATABASES = {
        "default": {
            "ENGINE":   "django.db.backends.postgresql_psycopg2",
            "HOST":     "localhost",
            "NAME":     DBNAME,
            "USER":     DBUSER,
            "PASSWORD": DBNAME
        }
    },
    DEBUG = DEV_BOX
)

appconf = {
    "/": {
        "tools.proxy.on": True,
        "tools.proxy.base": "http://{}".format(state.HOSTNAME),
        "tools.staticdir.root": os.getcwd()
    },
    "/static": {
        "tools.staticdir.on": True,
        "tools.staticdir.dir": "static"
    }
}

LOGGING_LEVELS = {
    "": INFO,
    "cherrypy.access": INFO,
    "cherrypy.error": DEBUG,
    "django.db.backends": INFO,
}
for logger,level in LOGGING_LEVELS.items():
    logging.getLogger(logger).setLevel(level)

log = logging.getLogger()
handler = logging.FileHandler("uber.log")
handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
log.addHandler(handler)
