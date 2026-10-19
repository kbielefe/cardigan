"""OpenTelemetry setup and request spans."""

from __future__ import annotations

import json
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.request import urlopen

from opentelemetry import trace
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pattern_import.server import make_server
from project import otel
from project.complete import MODEL, TIMEOUT, URL, _post
from project.env import apply_env, env_value, read_env
from project.parse import ParseFailure


def _stream_response(*texts: str, reasoning: str = ""):
    lines = []
    if reasoning:
        lines.append(
            f"data: {json.dumps({'choices': [{'delta': {'reasoning_content': reasoning}}]})}\n".encode()
        )
    for text in texts:
        lines.append(
            f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}\n".encode()
        )
    lines.append(b"data: [DONE]\n")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return iter(lines)

    return Response()

OTEL_KEYS = (
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_RESOURCE_ATTRIBUTES",
    "OTEL_TRACES_SAMPLER",
    "OTEL_TRACES_SAMPLER_ARG",
)


class EnvTests(unittest.TestCase):
    def test_read_env_strips_export_and_quotes(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                '# comment\nexport OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                read_env(path)["OTEL_EXPORTER_OTLP_ENDPOINT"],
                "http://127.0.0.1:4318",
            )
            self.assertEqual(
                env_value("OTEL_EXPORTER_OTLP_ENDPOINT", path),
                "http://127.0.0.1:4318",
            )

    def test_apply_env_loads_quoted_otel_keys(self):
        saved = {key: os.environ.pop(key, None) for key in OTEL_KEYS}
        try:
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / ".env"
                path.write_text(
                    "\n".join(
                        [
                            'OTEL_SERVICE_NAME="cardigan"',
                            'OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318"',
                            'OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"',
                            'OTEL_RESOURCE_ATTRIBUTES="deployment.environment=dev"',
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                apply_env(path, override=True)
                self.assertEqual(os.environ["OTEL_SERVICE_NAME"], "cardigan")
                self.assertEqual(
                    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"],
                    "http://127.0.0.1:4318",
                )
                self.assertEqual(os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"], "http/protobuf")
                self.assertEqual(
                    os.environ["OTEL_RESOURCE_ATTRIBUTES"],
                    "deployment.environment=dev",
                )
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class SetupTests(unittest.TestCase):
    def tearDown(self):
        otel.shutdown()

    def test_setup_is_quiet_without_endpoint(self):
        saved = {key: os.environ.pop(key, None) for key in OTEL_KEYS}
        try:
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / ".env"
                path.write_text("XAI_API_KEY=secret\n", encoding="utf-8")
                self.assertFalse(otel.setup(path))
                self.assertFalse(otel.active())
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_setup_reads_standard_otel_resource_keys(self):
        saved = {key: os.environ.pop(key, None) for key in OTEL_KEYS}
        try:
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / ".env"
                path.write_text(
                    "\n".join(
                        [
                            'OTEL_SERVICE_NAME="cardigan"',
                            'OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318"',
                            'OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"',
                            'OTEL_RESOURCE_ATTRIBUTES="deployment.environment=dev"',
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                self.assertTrue(otel.setup(path))
                resource = trace.get_tracer_provider().resource
                self.assertEqual(resource.attributes["service.name"], "cardigan")
                self.assertEqual(resource.attributes["deployment.environment"], "dev")
        finally:
            otel.shutdown()
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_setup_rejects_grpc_protocol(self):
        saved = {key: os.environ.pop(key, None) for key in OTEL_KEYS}
        try:
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / ".env"
                path.write_text(
                    "OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318\n"
                    "OTEL_EXPORTER_OTLP_PROTOCOL=grpc\n",
                    encoding="utf-8",
                )
                self.assertFalse(otel.setup(path))
                self.assertFalse(otel.active())
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_setup_defaults_sampler_and_installs_auto_instrumentation(self):
        saved = {key: os.environ.pop(key, None) for key in OTEL_KEYS}
        try:
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / ".env"
                path.write_text(
                    "OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318\n",
                    encoding="utf-8",
                )
                self.assertTrue(otel.setup(path))
                self.assertEqual(os.environ["OTEL_TRACES_SAMPLER"], "parentbased_always_on")
                self.assertTrue(URLLibInstrumentor().is_instrumented_by_opentelemetry)
                self.assertTrue(SQLite3Instrumentor().is_instrumented_by_opentelemetry)
        finally:
            otel.shutdown()
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class SpanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spans = InMemorySpanExporter()
        cls.metrics = InMemoryMetricReader()
        otel.setup_for_test(cls.spans, cls.metrics)

    @classmethod
    def tearDownClass(cls):
        otel.shutdown()

    def setUp(self):
        self.spans.clear()

    def test_http_request_records_span_and_status(self):
        server = make_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            urlopen(f"http://127.0.0.1:{port}/").read()
        finally:
            server.shutdown()
            server.server_close()
        names = [span.name for span in self.spans.get_finished_spans()]
        self.assertIn("GET /index.html", names)
        span = next(span for span in self.spans.get_finished_spans() if span.name == "GET /index.html")
        self.assertEqual(span.attributes["http.response.status_code"], 200)

    def test_llm_request_records_span(self):
        with patch("project.complete.urlopen", return_value=_stream_response("{}")) as mocked:
            body = _post({"model": MODEL, "messages": []}, "secret")
        self.assertEqual(body["choices"][0]["message"]["content"], "{}")
        self.assertEqual(mocked.call_args.kwargs["timeout"], TIMEOUT)
        outbound = json.loads(mocked.call_args.args[0].data.decode())
        self.assertTrue(outbound["stream"])
        span = next(span for span in self.spans.get_finished_spans() if span.name == f"chat {MODEL}")
        self.assertEqual(span.attributes["gen_ai.request.model"], MODEL)
        self.assertEqual(span.attributes["server.address"], URL)

    def test_llm_logs_request_and_response_at_debug(self):
        payload = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
        seen = []
        with patch("project.complete.urlopen", return_value=_stream_response("{", "}")):
            with self.assertLogs("cardigan", level="DEBUG") as logs:
                body = _post(payload, "secret", seen.append)
        self.assertEqual(body["choices"][0]["message"]["content"], "{}")
        self.assertEqual(seen, ["{", "}"])
        joined = "\n".join(logs.output)
        self.assertIn("llm request", joined)
        self.assertIn('"stream": true', joined)
        self.assertIn("hi", joined)
        self.assertIn("llm response {}", joined)
        self.assertNotIn("secret", joined)

    def test_llm_failure_marks_span_error(self):
        with patch("project.complete.urlopen", side_effect=TimeoutError):
            with self.assertRaises(ParseFailure):
                with self.assertLogs("cardigan", level="DEBUG") as logs:
                    _post({"model": MODEL, "messages": []}, "secret")
        span = next(span for span in self.spans.get_finished_spans() if span.name == f"chat {MODEL}")
        self.assertEqual(span.status.status_code.name, "ERROR")
        self.assertTrue(any("llm transport error" in line for line in logs.output))

    def test_operation_records_chart_span(self):
        with otel.operation("chart.from_image", {"chart.rows": 2, "chart.cols": 3}):
            pass
        span = next(span for span in self.spans.get_finished_spans() if span.name == "chart.from_image")
        self.assertEqual(span.attributes["chart.rows"], 2)
        self.assertEqual(span.attributes["chart.cols"], 3)


if __name__ == "__main__":
    unittest.main()
