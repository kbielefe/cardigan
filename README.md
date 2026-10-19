# Cardigan

Cardigan turns a written knitting pattern into carriage passes for the Silver Reed LK150 or the Taitexma TH-160 in front of the knitter. The same pattern word can name different levers and needle letters on each machine. `DOMAIN.md` is the authority for that resolution.

The working page is pattern import. Paste a pattern, give its address, or choose an HTML, PDF, or TXT file. The page keeps the pattern's own words. Pictures stay in place, and a chart picture becomes a grid of its colors. Accept freezes that reading and sends it to the model. Keys live in a `.env` file at the repo root: `XAI_API_KEY` for the model, and optional OpenTelemetry settings to export traces, metrics, and logs. The server turns telemetry on itself when `OTEL_EXPORTER_OTLP_ENDPOINT` is set — you do not need the `opentelemetry-instrument` wrapper. A parsed project is stored in `cardigan.sqlite` in the working directory.

OpenTelemetry `.env` keys (standard names):

- `OTEL_SERVICE_NAME` — defaults in code to `cardigan` when unset
- `OTEL_EXPORTER_OTLP_ENDPOINT` — collector base URL, e.g. `http://127.0.0.1:4318`
- `OTEL_EXPORTER_OTLP_PROTOCOL` — `http/protobuf` (required for Cardigan's exporter)
- `OTEL_RESOURCE_ATTRIBUTES` — e.g. `deployment.environment=dev`
- `OTEL_TRACES_SAMPLER` — defaults to `parentbased_always_on` (100%); use `parentbased_traceidratio` with `OTEL_TRACES_SAMPLER_ARG` (e.g. `0.1`) to sample

What is instrumented: inbound HTTP, outbound urllib (pattern fetch and LLM), sqlite3, chart reads, plus LLM-specific spans/metrics on model calls.

## Run

Python 3.13 or newer. PDF import calls `pdftohtml` from Poppler.

```
uv sync
uv run python -m pattern_import.server
```

The server prints `http://127.0.0.1:8765` and listens on localhost only. A port argument replaces 8765.

A chart image can be read on its own. Rows and columns are the squares in the picture.

```
uv run python -m pattern_import.chart IMAGE ROWS COLS
```

## Test

```
uv run python -m unittest project.test_store project.test_parse project.test_otel pattern_import.test_extract pattern_import.test_chart
```

## Reading

- `DOMAIN.md` is how pattern language collapses to actions, and how those actions become the levers and needle letters of each machine.
- `PRODUCT.md` is who it is for and what a finished pass is.
- `DESIGN.md` is the pattern-leaflet surface.
- `sources/README.md` is the manuals and patterns that reading follows.

`pattern_import/` is the local page and the code that extracts a reading and reads a chart. `project/` stores the pieces, sizes, and passes, and asks the model to read an accepted pattern. `sources/` holds the saved manuals, patterns, and abbreviation lists.
