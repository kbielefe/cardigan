"""Development check for the chart-pass prompt.

Not part of the regression suite. Run it by name:

    uv run python -m unittest project.dev_chart_passes

The grids are the fairisle charts. The reading rule is Clearwater method 1.
"""

from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pattern_import.chart import read_chart
from pattern_import.extract import extract_bytes
from pattern_import.test_chart import FAIRISLE
from project.complete import complete
from project.parse import ParseFailure
from project.stages.chart_passes import SCHEMA, SYSTEM, build_chart_passes, request_text

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources"
PDF = SOURCES / "patterns/eileen-montgomery-lk150-fairisle.pdf"
METHOD = SOURCES / "patterns/clearwater-lk150-fairisle-method-1.html"
PHRASE = "We will now knit this pattern,"
FOOTER = "Go to Fairisle Method 2"
DUMP = Path("/tmp/cardigan-chart-passes.json")
POOL = 4


def _light(hex_code: str) -> tuple[int, int, int, int]:
    red, green, blue = (int(hex_code[index : index + 2], 16) for index in (1, 3, 5))
    return (red + green + blue, red, green, blue)


def _runs(row: list[int], color: int) -> list[int]:
    found: list[int] = []
    count = 0
    for value in row:
        if value == color:
            count += 1
        elif count:
            found.append(count)
            count = 0
    if count:
        found.append(count)
    return found


def _row_passes(row: list[int], colors: dict[int, str]) -> list[list[int]]:
    present: list[int] = []
    for value in row:
        if value not in present:
            present.append(value)
    order = sorted(present, key=lambda index: _light(colors[index]))
    return [_runs(row, color) for color in order]


def _expected(grid: list[list[int]], colors: dict[int, str]) -> list[list[int]]:
    passes: list[list[int]] = []
    for row in reversed(grid):
        passes.extend(_row_passes(row, colors))
    return passes


def _charts() -> list[tuple[tuple[int, int, int], list[list[int]], dict[int, str], str]]:
    data = PDF.read_bytes()
    result = extract_bytes(data, PDF.name, "application/pdf")
    if not result.ok:
        raise AssertionError(result.message)
    found: dict[tuple[int, int, int], tuple[list[list[int]], dict[int, str], str]] = {}
    for part in result.parts:
        if part.kind == "grid":
            labels = "\n".join(cell.text for cell in part.cells if cell.kind == "text" and cell.text)
            for cell in part.cells:
                if cell.kind != "image" or not cell.data:
                    continue
                key = (part.page, cell.width, cell.height)
                if key not in FAIRISLE:
                    continue
                chart = read_chart(cell.data)
                if chart is None:
                    raise AssertionError(f"missing chart {key}")
                grid = [[int(value) for value in row] for row in chart.grid.tolist()]
                colors = {int(index): color for index, color in chart.colors.items()}
                found[key] = (grid, colors, labels)
        elif part.kind == "image" and part.data:
            key = (part.page, part.width, part.height)
            if key not in FAIRISLE or key in found:
                continue
            chart = read_chart(part.data)
            if chart is None:
                raise AssertionError(f"missing chart {key}")
            grid = [[int(value) for value in row] for row in chart.grid.tolist()]
            colors = {int(index): color for index, color in chart.colors.items()}
            found[key] = (grid, colors, "")
    missing = [key for key in FAIRISLE if key not in found]
    if missing:
        raise AssertionError(f"missing charts {missing}")
    return [(key, *found[key]) for key in FAIRISLE]


def _method() -> tuple[str, str]:
    data = METHOD.read_bytes()
    result = extract_bytes(data, METHOD.name, "text/html")
    if not result.ok:
        raise AssertionError(result.message)
    at = result.reading.find(PHRASE)
    if at < 0:
        raise AssertionError("the numbered steps are missing")
    steps = result.reading[at:]
    footer = steps.find(FOOTER)
    if footer >= 0:
        steps = steps[:footer]
    return result.reading[:at], steps


def _read(grid, colors, labels, description, steps) -> dict:
    corpus = "\n\n".join(part.strip() for part in (description, steps) if part.strip())
    content = request_text(labels=labels, description=description, steps=steps, grid=grid, colors=colors)
    try:
        payload = complete(
            content,
            schema=SCHEMA,
            system=SYSTEM,
            reasoning_effort="low",
            schema_name="chart_passes",
        )
        passes, repeats = build_chart_passes(corpus, payload)
    except ParseFailure as exc:
        cause = exc.__cause__
        return {"error": str(exc) if cause is None else f"{exc}: {cause}", "passes": None, "repeats": None}
    return {
        "error": None,
        "repeats": [{"first": item.first, "last": item.last, "times": item.times} for item in repeats],
        "passes": [_public_pass(corpus, step) for step in passes],
    }


def _public_pass(text: str, step) -> dict:
    return {
        "kind": step.kind,
        "count": step.count,
        "cite": text[step.cite_start : step.cite_end],
        "carriage_end": step.carriage_end,
        "open_point": step.open_point,
        "mark": step.mark,
        "selections": [
            {"role": item.role, "method": item.method, "count": item.count, "needle": item.needle}
            for item in step.selections
        ],
        "settings": [{"name": item.name, "scope": item.scope} for item in step.settings],
        "yarns": [{"place": item.place, "name": item.name} for item in step.yarns],
    }


def _letter(step: dict) -> str | None:
    mains = [item for item in step["yarns"] if item["place"] == "main"]
    if not mains or mains[0]["name"] is None:
        return None
    token = mains[0]["name"].strip().casefold()
    if token.startswith("yarn "):
        token = token[5:].strip()
    return token


def _counts(step: dict) -> list[int] | None:
    counts = []
    for item in step["selections"]:
        if item["role"] != "holding" or item["method"] != "stitch_count" or item["needle"] is not None:
            return None
        if type(item["count"]) is not int:
            return None
        counts.append(item["count"])
    return counts


def _judge(grid: list[list[int]], colors: dict[int, str], item: dict) -> list[str]:
    if item["error"]:
        return [item["error"]]
    problems = []
    passes = item["passes"]
    if item["repeats"]:
        problems.append(f"repeats {item['repeats']}")
    settings = [setting["name"] for step in passes for setting in step["settings"]]
    if "slip" not in settings:
        problems.append("side levers on the dot are not slip")
    if "knit_holding" not in settings:
        problems.append("Russel II is not knit holding")
    selected = [step for step in passes if step["selections"]]
    expected = _expected(grid, colors)
    got = []
    for step in selected:
        counts = _counts(step)
        if counts is None:
            problems.append("a selection is not a holding stitch count")
            return problems
        got.append(counts)
        if step["open_point"] != "chart_edge":
            problems.append(f"edge was treated as settled: {step['open_point']}")
        if any(item["method"] == "needle_number" for item in step["selections"]):
            problems.append("a square was stored as a needle number")
    if got != expected:
        problems.append(f"runs {got[:4]} != {expected[:4]}")
    if not selected:
        return problems
    if selected[0]["carriage_end"] != "left":
        problems.append(f"first row does not go left: {selected[0]['carriage_end']}")
    first_row = _row_passes(grid[-1], colors)
    if len(selected) > 1 and len(first_row) > 1 and selected[1]["carriage_end"] is not None:
        problems.append(f"second pass named an end: {selected[1]['carriage_end']}")
    for step in selected:
        end = step["carriage_end"]
        if end and end not in step["cite"].casefold():
            problems.append(f"carriage end {end} is not in the cite")
    offset = 0
    for row in reversed(grid):
        width = len(_row_passes(row, colors))
        chunk = selected[offset : offset + width]
        offset += width
        letters = [_letter(step) for step in chunk]
        if not letters or letters[0] != "a":
            problems.append(f"yarn A missing {letters}")
            break
        if len(letters) > 1 and letters[1] != "b":
            problems.append(f"yarn B missing {letters}")
            break
        if any(letter is not None for letter in letters[2:]):
            problems.append(f"a third color was named {letters}")
            break
    stored = " ".join((step["mark"] or "") for step in passes)
    stored += " " + " ".join((item["name"] or "") for step in passes for item in step["yarns"])
    if "russel" in stored.casefold():
        problems.append("Russel was stored")
    return problems


def _print_pass(index: int, step: dict) -> None:
    bits = [step["kind"], f"x{step['count']}"]
    if step["carriage_end"]:
        bits.append(step["carriage_end"])
    if step["open_point"]:
        bits.append(step["open_point"])
    bits.extend(item["name"] for item in step["settings"])
    for item in step["yarns"]:
        bits.append(item["name"] or "yarn")
    counts = _counts(step)
    if counts is not None and step["selections"]:
        bits.append("runs " + ",".join(str(count) for count in counts))
    cite = " ".join(step["cite"].split())
    if len(cite) > 70:
        cite = cite[:67] + "..."
    print(f"    [{index:02d}] {' '.join(bits)} | {cite}")


class ChartPassDevTests(unittest.TestCase):
    def test_fairisle_charts_follow_method_1(self) -> None:
        description, steps = _method()
        charts = _charts()
        found: dict[tuple[int, int, int], dict] = {}
        with ThreadPoolExecutor(max_workers=POOL) as pool:
            futures = {
                key: pool.submit(_read, grid, colors, labels, description, steps)
                for key, grid, colors, labels in charts
            }
            for key, future in futures.items():
                found[key] = future.result()

        report = []
        failures = []
        for key, grid, colors, _labels in charts:
            item = found[key]
            print(f"\n{key}")
            if item["passes"]:
                for index, step in enumerate(item["passes"]):
                    _print_pass(index, step)
            problems = _judge(grid, colors, item)
            for problem in problems:
                print(f"  ! {problem}")
                failures.append(f"{key}: {problem}")
            report.append({"chart": list(key), "error": item["error"], "passes": item["passes"], "repeats": item["repeats"]})

        DUMP.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\n{DUMP}")
        if failures:
            self.fail("\n".join(failures))


if __name__ == "__main__":
    unittest.main()
