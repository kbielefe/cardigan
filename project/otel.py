"""OpenTelemetry traces, metrics, and logs. Configured from standard OTEL_* `.env` keys.

The `opentelemetry-instrument` CLI wrapper is not required. ``setup()`` configures
the SDK from the environment and turns on urllib, sqlite3, and logging
auto-instrumentation in-process.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
)
from opentelemetry.semconv.attributes.url_attributes import URL_PATH
from opentelemetry.trace import Status, StatusCode

from project.env import apply_env

SERVICE_NAME = "cardigan"
ENDPOINT_KEY = "OTEL_EXPORTER_OTLP_ENDPOINT"
PROTOCOL_KEY = "OTEL_EXPORTER_OTLP_PROTOCOL"
SAMPLER_KEY = "OTEL_TRACES_SAMPLER"
HTTP_PROTOCOLS = frozenset({"http/protobuf", "http"})
DEFAULT_SAMPLER = "parentbased_always_on"

_log = logging.getLogger(SERVICE_NAME)
_active = False
_auto = False
_tracer = trace.get_tracer(SERVICE_NAME)
_meter = metrics.get_meter(SERVICE_NAME)
_providers: list = []
_http_duration = None
_http_count = None
_llm_duration = None
_llm_count = None


def active() -> bool:
    return _active


def setup(path: Path | None = None, *, endpoint: str | None = None) -> bool:
    """Turn on OTLP export when OTEL_EXPORTER_OTLP_ENDPOINT is set. Safe to call once."""
    global _active
    if _active:
        return True
    apply_env(path)
    _apply_defaults()
    _configure_log_level()
    if endpoint is not None:
        os.environ[ENDPOINT_KEY] = endpoint
    target = os.environ.get(ENDPOINT_KEY, "").strip()
    if not target:
        return False
    protocol = os.environ.get(PROTOCOL_KEY, "http/protobuf").strip() or "http/protobuf"
    if protocol not in HTTP_PROTOCOLS:
        _log.warning(
            "Unsupported %s=%s; Cardigan exports http/protobuf only",
            PROTOCOL_KEY,
            protocol,
        )
        return False
    # Resource.create reads OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES.
    # TracerProvider() reads OTEL_TRACES_SAMPLER / OTEL_TRACES_SAMPLER_ARG.
    resource = Resource.create()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[metric_reader], shutdown_on_exit=False
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)

    _providers.extend([tracer_provider, meter_provider, logger_provider])
    _bind_instruments()
    _install_auto_instrumentation()
    _active = True
    service = resource.attributes.get("service.name", SERVICE_NAME)
    sampler = os.environ.get(SAMPLER_KEY, DEFAULT_SAMPLER)
    _log.info(
        "OpenTelemetry service=%s sampler=%s exporting to %s",
        service,
        sampler,
        target.rstrip("/"),
    )
    return True


def setup_for_test(span_exporter, metric_reader, log_exporter=None) -> None:
    """Wire in-memory exporters for tests."""
    global _active
    shutdown()
    resource = Resource.create({"service.name": SERVICE_NAME})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource, metric_readers=[metric_reader], shutdown_on_exit=False
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    if log_exporter is not None:
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)

    _providers.extend([tracer_provider, meter_provider, logger_provider])
    _bind_instruments()
    _install_auto_instrumentation()
    _active = True


def shutdown() -> None:
    global _active, _tracer, _meter
    global _http_duration, _http_count, _llm_duration, _llm_count
    _uninstall_auto_instrumentation()
    providers = list(_providers)
    _providers.clear()
    _http_duration = _http_count = _llm_duration = _llm_count = None
    _active = False
    _reset_providers()
    for provider in providers:
        provider.shutdown()
    _tracer = trace.get_tracer(SERVICE_NAME)
    _meter = metrics.get_meter(SERVICE_NAME)


def _apply_defaults() -> None:
    os.environ.setdefault(SAMPLER_KEY, DEFAULT_SAMPLER)
    os.environ.setdefault(PROTOCOL_KEY, "http/protobuf")


def _configure_log_level() -> None:
    """Honor LOG_LEVEL from the environment; default root to INFO when unset."""
    name = os.environ.get("LOG_LEVEL", "").strip().upper()
    level = getattr(logging, name, None) if name else None
    root = logging.getLogger()
    if isinstance(level, int):
        root.setLevel(level)
    elif root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)


def _install_auto_instrumentation() -> None:
    """Same libraries the `opentelemetry-instrument` wrapper would patch."""
    global _auto
    if _auto:
        return
    URLLibInstrumentor().instrument()
    SQLite3Instrumentor().instrument()
    LoggingInstrumentor().instrument()
    _auto = True


def _uninstall_auto_instrumentation() -> None:
    global _auto
    if not _auto:
        return
    LoggingInstrumentor().uninstrument()
    SQLite3Instrumentor().uninstrument()
    URLLibInstrumentor().uninstrument()
    _auto = False


def _reset_providers() -> None:
    """Allow setup again after shutdown (tests and process teardown)."""
    from opentelemetry._logs import _internal as logs_internal
    from opentelemetry.metrics import _internal as metrics_internal
    from opentelemetry.util._once import Once

    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    metrics_internal._METER_PROVIDER = None
    metrics_internal._METER_PROVIDER_SET_ONCE = Once()
    proxy_meters = metrics_internal._PROXY_METER_PROVIDER
    with proxy_meters._lock:
        proxy_meters._real_meter_provider = None
        for meter in proxy_meters._meters:
            meter._real_meter = None
    logs_internal._LOGGER_PROVIDER = None
    logs_internal._LOGGER_PROVIDER_SET_ONCE = Once()


def _bind_instruments() -> None:
    global _tracer, _meter, _http_duration, _http_count, _llm_duration, _llm_count
    _tracer = trace.get_tracer(SERVICE_NAME)
    _meter = metrics.get_meter(SERVICE_NAME)
    _http_duration = _meter.create_histogram(
        "http.server.request.duration",
        unit="s",
        description="Duration of inbound HTTP requests",
    )
    _http_count = _meter.create_counter(
        "http.server.request.count",
        unit="{request}",
        description="Inbound HTTP requests",
    )
    _llm_duration = _meter.create_histogram(
        "gen_ai.client.operation.duration",
        unit="s",
        description="Duration of outbound LLM requests",
    )
    _llm_count = _meter.create_counter(
        "gen_ai.client.operation.count",
        unit="{request}",
        description="Outbound LLM requests",
    )


@contextmanager
def operation(name: str, attributes: dict | None = None) -> Iterator:
    """Trace a local unit of work when telemetry is active."""
    if not _active:
        yield None
        return
    with _tracer.start_as_current_span(name) as span:
        if attributes:
            span.set_attributes(attributes)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@contextmanager
def http_request(method: str, path: str) -> Iterator:
    """Trace, log, and measure one inbound HTTP request. Yields a status holder."""
    status = {"code": 500}
    if not _active:
        yield status
        return
    attributes = {HTTP_REQUEST_METHOD: method, URL_PATH: path}
    started = time.perf_counter()
    with _tracer.start_as_current_span(f"{method} {path}") as span:
        span.set_attributes(attributes)
        try:
            yield status
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            code = int(status["code"])
            span.set_attribute(HTTP_RESPONSE_STATUS_CODE, code)
            elapsed = time.perf_counter() - started
            outcome = status.get("outcome")
            message = status.get("message")
            labels = {**attributes, HTTP_RESPONSE_STATUS_CODE: code}
            if type(outcome) is str and outcome:
                span.set_attribute("accept.outcome", outcome)
                labels["accept.outcome"] = outcome
            if outcome == "error":
                text = message if type(message) is str else ""
                if text:
                    span.set_attribute("accept.error.message", text)
                span.set_status(Status(StatusCode.ERROR, text))
            elif code >= 500:
                span.set_status(Status(StatusCode.ERROR))
            if _http_duration is not None:
                _http_duration.record(elapsed, labels)
            if _http_count is not None:
                _http_count.add(1, labels)
            if outcome == "error" and type(message) is str and message:
                _log.info("%s %s %s %.3fs %s %s", method, path, code, elapsed, outcome, message)
            elif type(outcome) is str and outcome:
                _log.info("%s %s %s %.3fs %s", method, path, code, elapsed, outcome)
            else:
                _log.info("%s %s %s %.3fs", method, path, code, elapsed)


@contextmanager
def llm_request(model: str, url: str, attributes: dict | None = None) -> Iterator:
    """Trace, log, and measure one outbound LLM call. Yields the span, or None."""
    if not _active:
        yield None
        return
    labels = {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "xai",
        "gen_ai.request.model": model,
        "server.address": url,
    }
    if attributes:
        labels.update(attributes)
    started = time.perf_counter()
    with _tracer.start_as_current_span(f"chat {model}") as span:
        span.set_attributes(labels)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            if _llm_duration is not None:
                _llm_duration.record(time.perf_counter() - started, labels)
            if _llm_count is not None:
                _llm_count.add(1, {**labels, "error.type": type(exc).__name__})
            _log.warning("llm %s failed: %s", model, exc)
            raise
        elapsed = time.perf_counter() - started
        if _llm_duration is not None:
            _llm_duration.record(elapsed, labels)
        if _llm_count is not None:
            _llm_count.add(1, labels)
        _log.info("llm %s %.3fs", model, elapsed)
