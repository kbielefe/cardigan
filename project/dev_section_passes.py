"""Development check for the section-pass prompt.

Not part of the regression suite. Run it by name:

    uv run python -m unittest project.dev_section_passes

Reads the canned sections from the section-split and section-parse dumps.
"""

from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from project.complete import complete
from project.model import Size
from project.parse import ParseFailure
from project.stages.section_passes import SCHEMA, SYSTEM, build_sizes, request_text

SPLIT_DUMP = Path("/tmp/cardigan-section-split.json")
PARSE_DUMP = Path("/tmp/cardigan-section-parse.json")
PASS_DUMP = Path("/tmp/cardigan-section-passes.json")
POOL = 4


def _load(path: Path) -> list[dict]:
    if not path.is_file():
        raise AssertionError(f"missing {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if type(data) is not list or not data:
        raise AssertionError(f"{path} is empty")
    return data


def _knitting(parsed: dict) -> bool:
    return parsed.get("kind") in {"piece", "method"} and parsed.get("procedure") is True


def _context(rows: list[dict]) -> tuple[list[str], list[dict]]:
    names: list[str] = []
    glossary: list[dict] = []
    for row in rows:
        parsed = row["parsed"]
        if parsed.get("kind") == "sizes":
            names.extend(parsed.get("size_names") or [])
        if parsed.get("kind") == "glossary":
            glossary.extend(parsed.get("glossary") or [])
    return names, glossary


def _read(text: str, parsed: dict, size_names: list[str], glossary: list[dict]) -> dict:
    content = request_text(
        kind=parsed["kind"],
        heading=parsed.get("heading"),
        copies=parsed.get("copies"),
        size_names=size_names,
        glossary=glossary,
        text=text,
    )
    payload = complete(
        content,
        schema=SCHEMA,
        system=SYSTEM,
        reasoning_effort="low",
        schema_name="section_passes",
    )
    try:
        sizes = build_sizes(text, payload, size_names, parsed.get("heading"))
    except ParseFailure as exc:
        cause = exc.__cause__
        return {"payload": payload, "error": str(exc) if cause is None else f"{exc}: {cause}", "sizes": None}
    return {"payload": payload, "error": None, "sizes": [_public_size(text, size) for size in sizes]}


def _public_size(text: str, size: Size) -> dict:
    return {
        "name": size.name,
        "repeats": [{"first": repeat.first, "last": repeat.last, "times": repeat.times} for repeat in size.repeats],
        "passes": [_public_pass(text, step) for step in size.passes],
    }


def _public_pass(text: str, step) -> dict:
    return {
        "kind": step.kind,
        "count": step.count,
        "cite": text[step.cite_start : step.cite_end],
        "carriage_end": step.carriage_end,
        "row_counter": None if step.row_counter is None else {"kind": step.row_counter.kind, "value": step.row_counter.value},
        "open_point": step.open_point,
        "mark": step.mark,
        "selections": [
            {
                "role": item.role,
                "method": item.method,
                "count": item.count,
                "every": item.every,
                "needles_between": item.needles_between,
                "between_role": item.between_role,
                "needle": item.needle,
                "side": item.side,
            }
            for item in step.selections
        ],
        "settings": [{"name": item.name, "scope": item.scope} for item in step.settings],
        "shapes": [{"name": item.name, "count": item.count, "technique": item.technique} for item in step.shapes],
        "yarns": [{"place": item.place, "name": item.name} for item in step.yarns],
    }


def _numbers(size: dict) -> set[int]:
    found = {size_pass["count"] for size_pass in size["passes"]}
    for repeat in size["repeats"]:
        found.add(repeat["times"])
    for step in size["passes"]:
        counter = step["row_counter"]
        if counter is not None:
            found.add(counter["value"])
        for item in step["selections"]:
            if type(item["count"]) is int:
                found.add(item["count"])
            if type(item["every"]) is int:
                found.add(item["every"])
        for item in step["shapes"]:
            if type(item["count"]) is int:
                found.add(item["count"])
    return found


def _cites(size: dict) -> list[str]:
    return [step["cite"] for step in size["passes"]]


def _wrap_body(sizes: list[dict]) -> list[str]:
    problems = []
    names = [size["name"] for size in sizes]
    if names != ["XS-M", "L-2X", "3X-5X"]:
        problems.append(f"sizes {names}")
        return problems
    first = sizes[0]
    if not any(
        step["open_point"] == "extra_needle_side"
        and any(item["method"] == "extra" and item["side"] is None for item in step["selections"])
        for step in first["passes"]
    ):
        problems.append("extra needle has a side")
    wanted = (60, 67, 75)
    for size, times in zip(sizes, wanted):
        got = [repeat["times"] for repeat in size["repeats"]]
        if times not in got:
            problems.append(f"{size['name']} repeat times {got}")
    repeat = next((item for item in first["repeats"] if item["times"] == 60), None)
    if repeat is None:
        return problems
    span = first["passes"][repeat["first"] : repeat["last"] + 1]
    pulls = [
        step
        for step in span
        if step["kind"] == "setup"
        and any(item["method"] == "every_nth" and item["every"] == 4 and item["role"] == "holding" for item in step["selections"])
    ]
    knits = [step for step in span if step["kind"] == "trip" and step["count"] == 3]
    all_needles = [
        step
        for step in span
        if any(item["name"] == "knit_holding" for item in step["settings"])
        or any(item["method"] == "all" for item in step["selections"])
    ]
    if len(pulls) < 2:
        problems.append(f"every-4th setups inside the repeat: {len(pulls)}")
    if len(knits) < 2:
        problems.append(f"knit-3 trips inside the repeat: {len(knits)}")
    if len(all_needles) < 2:
        problems.append(f"knit-all frames inside the repeat: {len(all_needles)}")
    if any("i-cord" in cite.casefold() for cite in _cites(first)):
        problems.append("i-cord was cited")
    if not any(item["technique"] == "e-wrap" and item["name"] == "cast_on" for step in first["passes"] for item in step["shapes"]):
        problems.append("no e-wrap cast on")
    return problems


def _wrap_sleeve(sizes: list[dict]) -> list[str]:
    problems = []
    if [size["name"] for size in sizes] != ["XS-M", "L-2X", "3X-5X"]:
        problems.append(f"sizes {[size['name'] for size in sizes]}")
        return problems
    first = sizes[0]
    shapes = [item["name"] for step in first["passes"] for item in step["shapes"]]
    for name in ("cast_on", "transfer", "increase", "bind_off"):
        if name not in shapes:
            problems.append(f"no {name}")
    if not any(item["technique"] == "e-wrap" for step in first["passes"] for item in step["shapes"]):
        problems.append("cast on is not e-wrap")
    increases = (16, 38, 42)
    for size, count in zip(sizes, increases):
        if count not in _numbers(size):
            problems.append(f"{size['name']} increase count missing {count}")
    return problems


def _front(sizes: list[dict]) -> list[str]:
    problems = []
    names = ["XS", "S", "M", "L", "XL", "2X", "3X", "4X", "5X"]
    if [size["name"] for size in sizes] != names:
        problems.append(f"sizes {[size['name'] for size in sizes]}")
        return problems
    first, last = sizes[0], sizes[-1]
    if 62 not in _numbers(first) or 118 not in _numbers(last):
        problems.append("cast-on group is not split across the sizes")
    counters = [step["row_counter"] for step in first["passes"] if step["row_counter"] is not None]
    if not any(item["kind"] == "reset" and item["value"] == 0 for item in counters):
        problems.append("no RC 000")
    if not any(item["kind"] == "reset" and item["value"] == 76 for item in counters):
        problems.append("second side did not reset to 76")
    if not any(step["carriage_end"] == "right" and step["kind"] == "setup" for step in first["passes"]):
        problems.append("carriage on the right is not a setup")
    if not any(item["name"] == "short_row_wrap" for step in first["passes"] for item in step["shapes"]):
        problems.append("no short-row wrap")
    if not any(item["role"] == "holding" for step in first["passes"] for item in step["selections"]):
        problems.append("no needles in hold")
    odd_cast_on = any(
        step["open_point"] == "extra_needle_side" or any(item["method"] == "extra" for item in step["selections"])
        for step in first["passes"]
    )
    if odd_cast_on:
        problems.append("a center needle was read as the odd cast-on needle")
    cited = "\n".join(_cites(first)).casefold()
    if "do not cut yarn" not in cited and "hang needles" not in cited:
        problems.append("the neckline after the second side is missing")
    reset_at = next(
        (
            index
            for index, step in enumerate(first["passes"])
            if step["row_counter"] and step["row_counter"]["kind"] == "reset" and step["row_counter"]["value"] == 76
        ),
        None,
    )
    repeated = reset_at is not None and any(
        item["name"] == "short_row_wrap" for step in first["passes"][reset_at + 1 :] for item in step["shapes"]
    )
    if not repeated:
        problems.append("the second side does not repeat the shaping")
    return problems


def _simple_sleeve(sizes: list[dict]) -> list[str]:
    problems = []
    if len(sizes) != 9:
        problems.append(f"{len(sizes)} sizes")
        return problems
    first = sizes[0]
    shapes = [item["name"] for step in first["passes"] for item in step["shapes"]]
    for name in ("decrease", "transfer", "bind_off"):
        if name not in shapes:
            problems.append(f"no {name}")
    if any("make second sleeve" in cite.casefold() for cite in _cites(first)):
        problems.append("Make second sleeve was cited")
    return problems


def _fairisle(sizes: list[dict]) -> list[str]:
    problems = []
    if len(sizes) != 1:
        problems.append(f"{len(sizes)} sizes")
        return problems
    first = sizes[0]
    settings = [item["name"] for step in first["passes"] for item in step["settings"]]
    if "slip" not in settings:
        problems.append("side levers on the dot are not slip")
    if "knit_holding" not in settings:
        problems.append("Russel II is not knit holding")
    yarns = [item["name"] for step in first["passes"] for item in step["yarns"] if item["name"]]
    if not any(name.strip().casefold() in {"a", "yarn a"} for name in yarns):
        problems.append(f"no yarn A {yarns}")
    if not any(name.strip().casefold() in {"b", "yarn b"} for name in yarns):
        problems.append(f"no yarn B {yarns}")
    ends = [step["carriage_end"] for step in first["passes"]]
    if "left" not in ends or "right" not in ends:
        problems.append(f"carriage ends {ends}")
    stored = " ".join(yarns) + " " + " ".join(step["mark"] or "" for step in first["passes"])
    if "russel" in stored.casefold():
        problems.append("Russel was stored")
    return problems


def _blanket(sizes: list[dict], text: str) -> list[str]:
    problems = []
    if len(sizes) != 1:
        problems.append(f"{len(sizes)} sizes")
        return problems
    first = sizes[0]
    if not any(
        item["method"] == "every_nth" and item["every"] == 5 and item["role"] == "holding"
        for step in first["passes"]
        for item in step["selections"]
    ):
        problems.append("no every-5th hold")
    settings = [item["name"] for step in first["passes"] for item in step["settings"]]
    if "hold" not in settings:
        problems.append("Russell I is not hold")
    if "knit_holding" not in settings:
        problems.append("Russell II is not knit holding")
    if not any(step["kind"] == "trip" and step["count"] == 3 for step in first["passes"]):
        problems.append("no knit 3")
    cites = "\n".join(_cites(first)).casefold()
    if "amzn.to" in cites:
        problems.append("affiliate line was cited")
    if "tension is 9" in cites or "my tension" in cites:
        problems.append("tension number was cited")
    if "amzn.to" not in text.casefold() and "tension is 9" not in text.casefold():
        return problems
    return problems


def _judge(pattern: str, heading: str | None, text: str, sizes: list[dict]) -> list[str]:
    name = Path(pattern).name
    if name == "city-farmhouse-wrap-sweater-scarf.html" and heading == "Body":
        return _wrap_body(sizes)
    if name == "city-farmhouse-wrap-sweater-scarf.html" and heading == "Sleeve (make 2)":
        return _wrap_sleeve(sizes)
    if name == "city-farmhouse-simple-stitch-sweater.html" and heading == "Front":
        return _front(sizes)
    if name == "city-farmhouse-simple-stitch-sweater.html" and heading == "Sleeve":
        return _simple_sleeve(sizes)
    if name == "clearwater-lk150-fairisle-method-1.html":
        return _fairisle(sizes)
    if name == "creative-tien-lk150-tuck-blanket.html":
        return _blanket(sizes, text)
    return []


def _print_size(size: dict) -> None:
    print(f"  size {size['name']}")
    for index, step in enumerate(size["passes"]):
        bits = [step["kind"], f"x{step['count']}"]
        if step["carriage_end"]:
            bits.append(step["carriage_end"])
        if step["open_point"]:
            bits.append(step["open_point"])
        if step["row_counter"]:
            bits.append(f"{step['row_counter']['kind']} {step['row_counter']['value']}")
        bits.extend(item["name"] for item in step["settings"])
        bits.extend(item["name"] for item in step["shapes"])
        for item in step["selections"]:
            detail = item["method"]
            if item["every"] is not None:
                detail += f"/{item['every']}"
            if item["count"] is not None:
                detail += f"/{item['count']}"
            bits.append(f"{item['role']}:{detail}")
        cite = " ".join(step["cite"].split())
        if len(cite) > 70:
            cite = cite[:67] + "..."
        print(f"    [{index:02d}] {' '.join(bits)} | {cite}")
    for repeat in size["repeats"]:
        print(f"    repeat {repeat['first']}-{repeat['last']} x{repeat['times']}")


class SectionPassDevTests(unittest.TestCase):
    def test_canned_knitting_sections(self) -> None:
        split = _load(SPLIT_DUMP)
        parsed = _load(PARSE_DUMP)
        if len(split) != len(parsed):
            self.fail("split and parse dumps do not match")
        jobs = []
        for pattern_index, (source, reading) in enumerate(zip(split, parsed)):
            sections = source.get("sections")
            rows = reading.get("sections")
            if type(sections) is not list or type(rows) is not list or len(sections) != len(rows):
                self.fail(f"section counts differ for {source.get('pattern')}")
            size_names, glossary = _context(rows)
            for section_index, (text, row) in enumerate(zip(sections, rows)):
                if _knitting(row["parsed"]):
                    jobs.append((pattern_index, section_index, text, row["parsed"], size_names, glossary))

        found: dict[tuple[int, int], dict] = {}
        with ThreadPoolExecutor(max_workers=POOL) as pool:
            futures = {
                (pattern_index, section_index): pool.submit(_read, text, parsed_row, size_names, glossary)
                for pattern_index, section_index, text, parsed_row, size_names, glossary in jobs
            }
            for key, future in futures.items():
                found[key] = future.result()

        report = []
        failures = []
        for pattern_index, source in enumerate(split):
            pattern = source["pattern"]
            print(f"\n{pattern}")
            for section_index, text in enumerate(source["sections"]):
                key = (pattern_index, section_index)
                if key not in found:
                    continue
                item = found[key]
                heading = parsed[pattern_index]["sections"][section_index]["parsed"].get("heading")
                print(f"\n[{section_index:02d}] {heading!r}")
                if item["error"]:
                    print(f"  error {item['error']}")
                    failures.append(f"{Path(pattern).name} [{section_index}] {heading}: {item['error']}")
                else:
                    for size in item["sizes"]:
                        _print_size(size)
                    problems = _judge(pattern, heading, text, item["sizes"])
                    for problem in problems:
                        print(f"  ! {problem}")
                        failures.append(f"{Path(pattern).name} [{section_index}] {heading}: {problem}")
                report.append(
                    {
                        "pattern": pattern,
                        "index": section_index,
                        "heading": heading,
                        "error": item["error"],
                        "sizes": item["sizes"],
                    }
                )

        PASS_DUMP.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\n{PASS_DUMP}")
        if failures:
            self.fail("\n".join(failures))


if __name__ == "__main__":
    unittest.main()
