"""DOMAIN.md and Clearwater references for stage prompts and lookups."""

from __future__ import annotations

import re
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_PATH = ROOT / "DOMAIN.md"
ABBR_PATH = ROOT / "sources" / "references" / "clearwater-abbreviations.html"
SYMBOLS_PATH = ROOT / "sources" / "references" / "clearwater-stitch-symbols.html"

GLOSSARY_WINS = (
    "Abbreviation lists at Clearwater Knits and The Knit Tree both say machine-knitting "
    "abbreviations are not standard across publishers. The pattern's own glossary wins for that pattern."
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


@lru_cache(maxsize=1)
def _sections() -> dict[str, str]:
    text = DOMAIN_PATH.read_text(encoding="utf-8")
    headings: list[tuple[str, int]] = []
    for match in re.finditer(r"^(#{2,3}) (.+)$", text, re.MULTILINE):
        headings.append((match.group(2).strip(), match.start()))
    indexed: dict[str, str] = {}
    for index, (title, start) in enumerate(headings):
        end = headings[index + 1][1] if index + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        indexed[title.casefold()] = body
        short = title.split("(", 1)[0].strip()
        if short != title:
            indexed.setdefault(short.casefold(), body)
    return indexed


@lru_cache(maxsize=1)
def _html_text(path: Path) -> str:
    parser = _TextExtractor()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return re.sub(r"[ \t]+\n", "\n", "".join(parser.parts))


@lru_cache(maxsize=1)
def _clearwater_abbrs() -> dict[str, str]:
    text = _html_text(ABBR_PATH)
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = re.sub(r"[\xa0\t]+", " ", raw).strip()
        if not line or len(line) > 120:
            continue
        match = re.match(
            r"^([A-Za-z][A-Za-z0-9./+\-]{0,24}(?:/[A-Za-z][A-Za-z0-9./+\-]{0,24})?)\s{2,}(.+)$",
            line,
        )
        if not match:
            match = re.match(r"^([A-Z][A-Z0-9./\-]{0,12})\s+(.+)$", line)
        if not match:
            continue
        token = match.group(1).strip()
        expansion = match.group(2).strip()
        if len(expansion) < 2:
            continue
        found.setdefault(token.casefold(), expansion)
        found.setdefault(token, expansion)
    return found


def get_domain_section(heading: str) -> str:
    """Return one DOMAIN.md section by heading, or empty string."""
    if type(heading) is not str or not heading.strip():
        return ""
    return _sections().get(heading.strip().casefold(), "")


def inject(*headings: str) -> str:
    """Join named DOMAIN sections for a stage prompt."""
    parts = [get_domain_section(heading) for heading in headings]
    return "\n\n".join(part for part in parts if part)


def lookup_abbreviation(token: str) -> str | None:
    """Look up a Clearwater abbreviation. Pattern glossary still wins in prompts."""
    if type(token) is not str or not token.strip():
        return None
    table = _clearwater_abbrs()
    return table.get(token.strip()) or table.get(token.strip().casefold())


def abbreviations_in_text(text: str) -> list[tuple[str, str]]:
    """Tokens from the reading that match Clearwater, for orchestrator injection."""
    if type(text) is not str or not text:
        return []
    table = _clearwater_abbrs()
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9./\-]{0,12}\b", text):
        token = match.group(0)
        key = token.casefold()
        if key in seen:
            continue
        expansion = table.get(token) or table.get(key)
        if expansion is None:
            continue
        seen.add(key)
        found.append((token, expansion))
    return found


def stitch_symbols() -> str:
    """Plain text of the Clearwater stitch-symbol reference."""
    return _html_text(SYMBOLS_PATH)


def clearwater_abbreviations_text() -> str:
    """Plain text of the Clearwater abbreviations page."""
    return _html_text(ABBR_PATH)
