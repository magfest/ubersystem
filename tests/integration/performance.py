import pytest
import requests
import psutil
import time
import json
import pytest
import logging
import threading
import time
import cherrypy
from redis import Redis
from sqlalchemy import event, create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
from testcontainers.rabbitmq import RabbitMqContainer

import uber.config
import uber.models

class PerformanceTracker:
    def __init__(self, engine, process_pid):
        self.query_count = 0
        self.process = psutil.Process(process_pid)
        # Hook into SQLAlchemy to count statements
        @event.listens_for(engine, "before_cursor_execute")
        def count_queries(conn, cursor, statement, parameters, context, executemany):
            self.query_count += 1

    def get_metrics(self):
        return {
            "memory_mb": self.process.memory_info().rss / (1024 * 1024),
            "queries": self.query_count
        }

@pytest.fixture(scope="session")
def rams():
    postgres = PostgresContainer("postgres:15-alpine")
    redis = RedisContainer("redis:7-alpine")
    
    with postgres, redis:
        # 1. Update your app config with these dynamic ports
        db_url = postgres.get_connection_url()
        
        test_port = 8080
        cherrypy.config.update({
            "tools.sessions.host": redis.get_container_host_ip(),
            "tools.sessions.port": redis.get_exposed_port(6379),
            "tools.sessions.db": 0,
            'server.socket_host': '0.0.0.0',
            'server.socket_port': test_port,
            'environment': 'test_suite'
        })
        uber.config.c.REDIS_STORE = Redis(
            host=redis.get_container_host_ip(),
            port=redis.get_exposed_port(6379),
            db=0,
            decode_responses=True
        )
        
        new_engine = create_engine(
            db_url,
            pool_size=uber.config.c.SQLALCHEMY_POOL_SIZE,
            max_overflow=uber.config.c.SQLALCHEMY_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=uber.config.c.SQLALCHEMY_POOL_RECYCLE,
        )
        
        # Replace the global engine reference in the models module
        if uber.models.engine:
            uber.models.engine.dispose()
        uber.models.engine = new_engine
        
        # Replace the global sessionfactory
        new_factory = sessionmaker(
            bind=new_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=uber.models.UberSession,
            query_cls=uber.models.UberSession.QuerySubclass
        )
        
        # Patch the global Session registry/proxy with the new factory
        uber.models._ScopedSession = scoped_session(new_factory)
        uber.models._ScopedSession.model_mixin = uber.models.UberSession.model_mixin
        uber.models._ScopedSession.all_models = uber.models.UberSession.all_models
        uber.models._ScopedSession.engine = new_engine
        uber.models._ScopedSession.BaseClass = uber.models.DeclarativeBase
        uber.models._ScopedSession.SessionMixin = uber.models.UberSession.SessionMixin
        uber.models._ScopedSession.session_factory = new_factory
        class HybridSessionProxy:
            """
            A smart proxy that mimics the old Session class behavior.
            """
            def __getattr__(self, name):
                """
                Return thread-scoped session as expected by modern sqlalchemy usage on 'Session.query()'
                """
                return getattr(uber.models._ScopedSession, name)

            def __call__(self, *args, **kwargs):
                """
                Create isolated session, to match old behavior on 'with Session() as session'
                """
                return new_factory(*args, **kwargs)
        uber.models.Session = HybridSessionProxy()
        
        uber.models.engine = new_engine
        uber.models.Session.session_factory = new_factory
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
        def capture_queries(conn, cursor, statement, parameters, context, executemany):
            print(statement)

        # 3. Attach the listener to your engine
        event.listen(new_engine, "before_cursor_execute", capture_queries)
        
        for model in uber.models.Session.all_models():
            if not hasattr(uber.models.Session.SessionMixin, model.__tablename__):
                setattr(uber.models.Session.SessionMixin, model.__tablename__, uber.models._make_getter(model))
        uber.models.MagModel.metadata.create_all(new_engine)

        server_thread = threading.Thread(target=cherrypy.engine.start)
        server_thread.daemon = True
        server_thread.start()
        
        api_url = f"http://localhost:{test_port}"
        wait_for_server(api_url)

        # Yield control to the tests
        yield {
            "api_url": api_url,
            "db_url": db_url,
            "session_factory": new_factory,
            "engine": new_engine,
            "Session": uber.models.Session,
        }

        cherrypy.engine.exit()
        cherrypy.engine.block()

def wait_for_server(url, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Poll a known health endpoint or root
            requests.get(url)
            return
        except requests.ConnectionError:
            time.sleep(0.1)
    raise RuntimeError("Server failed to start")

# --- The Core Test Logic ---

def test_config_driven_scenarios(rams):
    url = rams["api_url"]
    Session = rams["Session"]
    with Session() as session:
        accounts = session.query(uber.models.AdminAccount).all()
        assert len(accounts) == 0
    assert requests.get(f"{url}/accounts/insert_test_admin").status_code == 200
    with Session() as session:
        accounts = session.query(uber.models.AdminAccount).all()
        assert len(accounts) == 1
    