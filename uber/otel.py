import time
import logging
from opentelemetry import trace, metrics, _logs
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.wsgi import OpenTelemetryMiddleware
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.jinja2 import Jinja2Instrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from sqlalchemy import event
import cherrypy
import logging
import psutil
import os

from uber.config import c

log = logging.getLogger(__name__)


# Track DB and Resource metrics per request
import threading
request_metrics = threading.local()

def get_request_metrics():
    if not hasattr(request_metrics, 'data'):
        request_metrics.data = {
            'db_queries': 0,
            'db_rows': 0,
            'db_time': 0.0,
            'template_time': 0.0,
            'start_thread_cpu': 0.0,
            'start_rss': 0
        }
    return request_metrics.data

def reset_request_metrics():
    process = psutil.Process(os.getpid())
    request_metrics.data = {
        'db_queries': 0,
        'db_rows': 0,
        'db_time': 0.0,
        'template_time': 0.0,
        'start_thread_cpu': time.thread_time(),
        'start_rss': process.memory_info().rss
    }

_initialized = False
_instrument_engine = None

def init_otel():
    global _initialized, _instrument_engine
    if _initialized:
        return _instrument_engine

    if not c.OTEL.get('enabled'):
        print("OpenTelemetry is disabled.")
        return None

    deployment_environment = c.OTEL.get('server_name')
    endpoint = c.OTEL.get('endpoint')
    exporter_url = endpoint + "/traces"

    def create_tracer_provider(service_name):
        resource = Resource.create({
            "service.name": service_name,
            "server.name": service_name,
            "deployment.environment": deployment_environment
        })
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=exporter_url)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        return provider

    # Create separate tracer providers for HTTP, DB, and Jinja to distinguish them in the flamegraph
    http_provider = create_tracer_provider("http")
    db_provider = create_tracer_provider("db")
    jinja_provider = create_tracer_provider("jinja")
    requests_provider = create_tracer_provider("requests")

    # Set the default global tracer provider to the HTTP one
    trace.set_tracer_provider(http_provider)

    # Metrics
    metric_resource = Resource.create({
        "service.name": "http",
        "server.name": "http",
        "deployment.environment": deployment_environment
    })
    metric_exporter = OTLPMetricExporter(endpoint=endpoint + "/metrics")
    metric_reader = PeriodicExportingMetricReader(metric_exporter)
    meter_provider = MeterProvider(resource=metric_resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # Instrument Jinja2 and Requests with their own providers
    Jinja2Instrumentor().instrument(tracer_provider=jinja_provider)
    RequestsInstrumentor().instrument(tracer_provider=requests_provider)

    # Configure Logging as OTLP Log Records
    logger_provider = LoggerProvider(resource=metric_resource)
    _logs.set_logger_provider(logger_provider)
    log_exporter = OTLPLogExporter(endpoint=endpoint + "/logs")
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    
    # Add handler to bridge python logging to OTel Logs
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)

    # Define a wrapper middleware for logging
    class LoggingOTelMiddleware(OpenTelemetryMiddleware):
        def __init__(self, app):
            super().__init__(app, tracer_provider=http_provider)

    # Metrics
    meter = metrics.get_meter("http")
    
    request_duration = meter.create_histogram(
        "http.server.duration",
        unit="ms",
        description="Duration of HTTP requests"
    )
    
    db_queries_counter = meter.create_counter(
        "db.queries",
        description="Number of DB queries"
    )

    db_rows_counter = meter.create_counter(
        "db.rows_retrieved",
        description="Number of rows retrieved from DB"
    )

    db_wait_time = meter.create_histogram(
        "db.wait_time",
        unit="ms",
        description="Time spent waiting for DB"
    )

    template_render_time = meter.create_histogram(
        "template.render_time",
        unit="ms",
        description="Time spent rendering templates"
    )

    bytes_returned = meter.create_histogram(
        "http.server.bytes_returned",
        unit="bytes",
        description="Bytes returned to client"
    )

    # SQLAlchemy instrumentation with custom hooks
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._start_time = time.time()

    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        duration = (time.time() - context._start_time) * 1000
        data = get_request_metrics()
        data['db_queries'] += 1
        data['db_time'] += duration
        
        # Try to get row count if possible
        try:
            if cursor.rowcount != -1:
                data['db_rows'] += cursor.rowcount
        except Exception:
            pass
    
    def instrument_engine(engine):
        SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=db_provider)
        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        event.listen(engine, "after_cursor_execute", after_cursor_execute)

    def set_request_attributes():
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            try:
                # Construct the full URL for http.url
                url = cherrypy.request.base + cherrypy.request.path_info
                full_url = url
                if cherrypy.request.query_string:
                    full_url += '?' + cherrypy.request.query_string
                
                current_span.set_attribute("http.url", url)
                current_span.set_attribute("url.full", full_url)

                # Get the Python view function path for http.route
                handler = cherrypy.request.handler
                
                # Unwrap common wrappers
                while True:
                    if hasattr(handler, 'callable'):
                        handler = handler.callable
                    elif hasattr(handler, 'page_handler'):
                        handler = handler.page_handler
                    elif hasattr(handler, '__wrapped__'):
                        handler = handler.__wrapped__
                    elif hasattr(handler, 'func') and hasattr(handler, 'args'): # Partial
                         handler = handler.func
                    else:
                        break
                
                route = None
                if handler and not isinstance(handler, tuple):
                    # If it's a bound method, we want the function itself
                    if hasattr(handler, '__func__'):
                        handler = handler.__func__
                    
                    # Try to get the fully qualified name
                    if hasattr(handler, '__module__') and hasattr(handler, '__name__'):
                        route = f"{handler.__module__}.{handler.__name__}"
                
                # Fallback if we couldn't get a proper name or if handler was a tuple/error
                if not route:
                    route = cherrypy.request.path_info
                    
                current_span.set_attribute("http.route", route)
            except Exception:
                pass

    def record_otel_metrics():
        data = get_request_metrics()
        process = psutil.Process(os.getpid())
        
        current_span = trace.get_current_span()
        if current_span:
            current_span.set_attribute("db.queries", data['db_queries'])
            current_span.set_attribute("db.rows", data['db_rows'])
            current_span.set_attribute("db.time_ms", data['db_time'])
            current_span.set_attribute("template.time_ms", data['template_time'])
            
            # Resource usage metrics
            cpu_delta_ms = (time.thread_time() - data['start_thread_cpu']) * 1000
            mem_current_rss = process.memory_info().rss
            mem_delta_bytes = mem_current_rss - data['start_rss']
            
            current_span.set_attribute("request.cpu_time_ms", cpu_delta_ms)
            current_span.set_attribute("process.memory.rss_total_bytes", mem_current_rss)
            current_span.set_attribute("process.memory.rss_delta_bytes", mem_delta_bytes)
            
            labels = {
                "method": cherrypy.request.method,
                "path": cherrypy.request.path_info,
                "status": str(cherrypy.response.status)
            }
            db_queries_counter.add(data['db_queries'], labels)
            db_rows_counter.add(data['db_rows'], labels)
            db_wait_time.record(data['db_time'], labels)
            template_render_time.record(data['template_time'], labels)
            
            content_length = cherrypy.response.headers.get('Content-Length')
            if content_length:
                try:
                    bytes_returned.record(int(content_length), labels)
                    current_span.set_attribute("http.response_content_length", int(content_length))
                except Exception:
                    pass

    cherrypy.tools.otel_request_attrs = cherrypy.Tool('before_handler', set_request_attributes, priority=50)
    cherrypy.tools.otel_metrics = cherrypy.Tool('on_end_request', record_otel_metrics, priority=95)
    cherrypy.tools.otel_reset = cherrypy.Tool('on_start_resource', reset_request_metrics, priority=5)

    _initialized = True
    _instrument_engine = {
        'instrument_engine': instrument_engine,
        'OpenTelemetryMiddleware': LoggingOTelMiddleware
    }
    return _instrument_engine
