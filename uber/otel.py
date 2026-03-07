import time
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.wsgi import OpenTelemetryMiddleware
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.jinja2 import Jinja2Instrumentor
from sqlalchemy import event
import cherrypy
import logging

from uber.config import c

log = logging.getLogger(__name__)

class SpanEventHandler(logging.Handler):
    """
    A logging handler that adds log records as events to the current OpenTelemetry span.
    This ensures that logs emitted during a request are 'attached' to the trace in SigNoz.
    """
    def emit(self, record):
        try:
            span = trace.get_current_span()
            if span and span.is_recording():
                # Mark span status as error for ERROR or higher logs
                if record.levelno >= logging.ERROR:
                    span.set_status(trace.Status(trace.StatusCode.ERROR, record.getMessage()))

                msg = self.format(record)
                
                # If there's exception info, record it properly
                if record.exc_info:
                    span.record_exception(
                        exception=record.exc_info[1],
                        attributes={
                            "log.severity": record.levelname,
                            "log.message": record.getMessage(),
                            "log.target": record.name,
                        }
                    )
                else:
                    span.add_event(
                        name="log",
                        attributes={
                            "log.severity": record.levelname,
                            "log.message": record.getMessage(),
                            "log.target": record.name,
                            "log.formatted": msg
                        }
                    )
        except Exception:
            pass


# Track DB metrics per request
import threading
request_metrics = threading.local()

def get_request_metrics():
    if not hasattr(request_metrics, 'data'):
        request_metrics.data = {
            'db_queries': 0,
            'db_rows': 0,
            'db_time': 0.0,
            'template_time': 0.0
        }
    return request_metrics.data

def reset_request_metrics():
    request_metrics.data = {
        'db_queries': 0,
        'db_rows': 0,
        'db_time': 0.0,
        'template_time': 0.0
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

    resource = Resource.create({"service.name": c.OTEL.get('server_name')})
    tracer_provider = TracerProvider(resource=resource)
    
    exporter = OTLPSpanExporter(endpoint=c.OTEL.get('endpoint')+"/traces")
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_exporter = OTLPMetricExporter(endpoint=c.OTEL.get('endpoint')+"/metrics")
    metric_reader = PeriodicExportingMetricReader(metric_exporter)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # Instrument Jinja2
    Jinja2Instrumentor().instrument()

    # Add log events to spans
    handler = SpanEventHandler()
    handler.setFormatter(logging.Formatter('%(name)s - %(message)s'))
    logging.getLogger().addHandler(handler)

    # Define a wrapper middleware for logging
    class LoggingOTelMiddleware(OpenTelemetryMiddleware):
        def __init__(self, app):
            super().__init__(app, tracer_provider=trace.get_tracer_provider())

    # Metrics
    meter = metrics.get_meter(c.OTEL.get('server_name'))
    
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
        SQLAlchemyInstrumentor().instrument(engine=engine)
        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        event.listen(engine, "after_cursor_execute", after_cursor_execute)

    def record_otel_metrics():
        data = get_request_metrics()
        
        current_span = trace.get_current_span()
        if current_span:
            current_span.set_attribute("db.queries", data['db_queries'])
            current_span.set_attribute("db.rows", data['db_rows'])
            current_span.set_attribute("db.time_ms", data['db_time'])
            current_span.set_attribute("template.time_ms", data['template_time'])
            
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

    cherrypy.tools.otel_metrics = cherrypy.Tool('on_end_request', record_otel_metrics, priority=95)
    cherrypy.tools.otel_reset = cherrypy.Tool('on_start_resource', reset_request_metrics, priority=5)

    _initialized = True
    _instrument_engine = {
        'instrument_engine': instrument_engine,
        'OpenTelemetryMiddleware': LoggingOTelMiddleware
    }
    return _instrument_engine
