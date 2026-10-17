"""Turn a page, an HTML file, a PDF, or a TXT file into the pattern's words and pictures.

A glossary stays in the reading with the rest of the pattern. Pictures from
the pattern stay in place. Nothing here is resolved into passes.
"""

from __future__ import annotations

import base64
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

MSG_FETCH = "This address did not come back. Check it, or paste the pattern."
MSG_URL_TYPE = "Cardigan takes a page, a PDF, or a TXT file."
MSG_FILE_TYPE = "Cardigan takes an HTML file, a PDF, or a TXT file."
MSG_SCAN = (
    "This PDF has no selectable text. Cardigan does not read a scan. "
    "Paste the pattern."
)

MAX_BYTES = 20 * 1024 * 1024
FETCH_TIMEOUT = 20
LINE_SLACK = 8
PARAGRAPH_GAP = 28
LABEL_CHARS = 16
LABEL_WORDS = 3
LABEL_WIDTH = 80
ROW_GAP = 26
MIN_GRID_ROWS = 4
GRID_GUTTER = 24
CHROME_HEADINGS = {
    "latest posts",
    "you may also like",
    "related posts",
    "leave a reply",
    "join our email newsletter",
    "join our newsletter",
    "newsletter signup",
    "site information",
    "social links",
    "follow us on socials",
}
CHROME_BITS = (
    "comment",
    "widget",
    "sharedaddy",
    "related-post",
    "latest-posts",
    "newsletter",
    "mailerlite",
    "sidebar",
    "breadcrumb",
    "screen-reader",
    "tasty-pins",
    "cookie",
    "popup",
    "post-tags",
    "post-meta",
    "entry-meta",
    "subscribe",
)
DROP_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "form",
    "nav",
    "header",
    "footer",
    "aside",
    "template",
    "button",
}
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "figcaption"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass
class Cell:
    kind: str
    text: str = ""
    src: str = ""
    data: bytes = b""
    media_type: str = ""
    top: int = 0
    left: int = 0
    width: int = 0
    height: int = 0
    chart: dict | None = None

    def as_dict(self) -> dict:
        item = {
            "kind": self.kind,
            "top": self.top,
            "left": self.left,
            "width": self.width,
            "height": self.height,
        }
        if self.kind == "text":
            item["text"] = self.text
        else:
            item["src"] = self._src()
            if self.chart:
                item["chart"] = self.chart
        return item

    def _src(self) -> str:
        if self.src:
            return self.src
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.media_type};base64,{encoded}"


@dataclass
class Part:
    kind: str
    text: str = ""
    src: str = ""
    data: bytes = b""
    media_type: str = ""
    page: int | None = None
    top: int | None = None
    left: int | None = None
    width: int | None = None
    height: int | None = None
    cells: list[Cell] = field(default_factory=list)
    chart: dict | None = None

    def as_dict(self) -> dict:
        if self.kind == "text":
            return {"kind": "text", "text": self.text}
        if self.kind == "grid":
            return {
                "kind": "grid",
                "page": self.page,
                "top": self.top,
                "left": self.left,
                "width": self.width,
                "height": self.height,
                "cells": [cell.as_dict() for cell in self.cells],
            }
        item = {"kind": "image", "src": self._src()}
        if self.page is not None:
            item["page"] = self.page
            item["top"] = self.top
            item["left"] = self.left
            item["width"] = self.width
            item["height"] = self.height
        if self.chart:
            item["chart"] = self.chart
        return item

    def _src(self) -> str:
        if self.src:
            return self.src
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.media_type};base64,{encoded}"


@dataclass
class Result:
    ok: bool
    reading: str = ""
    parts: list[Part] = field(default_factory=list)
    source: str = ""
    code: str = ""
    message: str = ""

    def as_dict(self) -> dict:
        if not self.ok:
            return {"ok": False, "code": self.code, "message": self.message}
        return {
            "ok": True,
            "reading": self.reading,
            "parts": [part.as_dict() for part in self.parts],
            "source": self.source,
        }


class El:
    def __init__(self, tag: str, attrs: list[tuple[str, str | None]]):
        self.tag = tag
        self.attrs = {key: value or "" for key, value in attrs}
        self.children: list[El | str] = []


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = El("document", [])
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag = tag.lower()
        if self.skip:
            if tag in {"script", "style"}:
                self.skip += 1
            return
        if tag in {"script", "style"}:
            self.skip = 1
            return
        el = El(tag, attrs)
        self.stack[-1].children.append(el)
        if tag not in VOID_TAGS:
            self.stack.append(el)

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if self.skip:
            if tag in {"script", "style"}:
                self.skip = max(0, self.skip - 1)
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str):
        if self.skip or not data:
            return
        self.stack[-1].children.append(data)


def clean(value: str) -> str:
    value = value.replace("\xa0", " ").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def norm_heading(value: str) -> str:
    first = clean(value).split("\n", 1)[0]
    first = first.strip(" :!?.").lower()
    return re.sub(r"\s+", " ", first)


def _blob(el: El) -> str:
    return f"{el.attrs.get('class', '')} {el.attrs.get('id', '')}".lower()


def _hidden(el: El) -> bool:
    style = re.sub(r"\s+", "", el.attrs.get("style", "")).lower()
    if "display:none" in style:
        return True
    blob = _blob(el)
    return "tasty-pins-hidden" in blob or "hidden-image" in blob


def _chrome(el: El) -> bool:
    if el.tag in DROP_TAGS:
        return True
    blob = _blob(el)
    if any(bit in blob for bit in CHROME_BITS):
        return True
    if el.tag in HEADING_TAGS and norm_heading(_text(el, chrome=False)) in CHROME_HEADINGS:
        return True
    return False


def _text(el: El, chrome: bool = True) -> str:
    parts: list[str] = []
    for child in el.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n")
        elif child.tag == "img":
            continue
        elif chrome and (_chrome(child) or _hidden(child)):
            continue
        else:
            parts.append(_text(child, chrome))
    return "".join(parts)


def _has_block(el: El) -> bool:
    for child in el.children:
        if not isinstance(child, El) or _chrome(child) or _hidden(child):
            continue
        if child.tag in BLOCK_TAGS or _has_block(child):
            return True
    return False


def _has_image(el: El) -> bool:
    if _chrome(el) or _hidden(el):
        return False
    if el.tag == "img":
        return True
    return any(isinstance(child, El) and _has_image(child) for child in el.children)


def _walk_blocks(el: El | str, out: list[El | str]):
    if isinstance(el, str):
        if el.strip():
            out.append(el)
        return
    if _chrome(el) or _hidden(el):
        return
    if el.tag == "img":
        out.append(el)
        return
    if el.tag in BLOCK_TAGS:
        out.append(el)
        return
    if _has_block(el) or _has_image(el):
        for child in el.children:
            _walk_blocks(child, out)
        return
    if clean(_text(el)):
        out.append(el)


def _image_url(src: str, base_url: str) -> str:
    src = src.strip()
    if not src:
        return ""
    if src.startswith("//"):
        src = "https:" + src
    if src.startswith("data:image/"):
        return src
    parsed = urlparse(src)
    if parsed.scheme in {"http", "https"}:
        return src
    if parsed.scheme or not base_url:
        return ""
    resolved = urljoin(base_url, src)
    if urlparse(resolved).scheme not in {"http", "https"}:
        return ""
    return resolved


def _block_parts(block: El | str, base_url: str) -> list[Part]:
    if isinstance(block, str):
        text = clean(block)
        return [Part("text", text=text)] if text else []
    parts: list[Part] = []
    buf: list[str] = []

    def flush():
        text = clean("".join(buf))
        buf.clear()
        if text:
            parts.append(Part("text", text=text))

    def walk(node: El | str):
        if isinstance(node, str):
            buf.append(node)
            return
        if node.tag == "br":
            buf.append("\n")
            return
        if node.tag == "img":
            src = _image_url(node.attrs.get("src", ""), base_url)
            if not src:
                return
            flush()
            parts.append(Part("image", src=src))
            return
        if _chrome(node) or _hidden(node):
            return
        for child in node.children:
            walk(child)

    walk(block)
    flush()
    return parts


def _find(el: El, pred) -> El | None:
    if pred(el):
        return el
    for child in el.children:
        if isinstance(child, El):
            found = _find(child, pred)
            if found is not None:
                return found
    return None


def _classes(el: El) -> set[str]:
    return set(el.attrs.get("class", "").split())


def _content_root(tree: El) -> El:
    article = _find(
        tree,
        lambda el: el.tag == "article" and "comment" not in _blob(el),
    )
    content = None
    if article is not None:
        content = _find(
            article,
            lambda el: "entry-content" in _classes(el) or "post-content" in _classes(el),
        )
    if content is None:
        content = _find(tree, lambda el: el.tag == "main")
    if content is None and article is not None:
        content = article
    if content is None:
        content = _find(tree, lambda el: el.tag == "body") or tree
    return content


def _first_h1(el: El) -> str:
    found = _find(el, lambda node: node.tag == "h1")
    return clean(_text(found)) if found is not None else ""


def _row_text(cells: list[Cell]) -> str:
    rows: list[list[str]] = []
    tops: list[int] = []
    for cell in sorted(cells, key=lambda item: (item.top, item.left)):
        if cell.kind != "text" or not cell.text.strip():
            continue
        if tops and abs(cell.top - tops[-1]) <= LINE_SLACK:
            rows[-1].append(cell.text.strip())
        else:
            tops.append(cell.top)
            rows.append([cell.text.strip()])
    return "\n".join(" ".join(words) for words in rows)


def _reading_text(parts: list[Part]) -> str:
    chunks: list[str] = []
    for part in parts:
        if part.kind == "text" and part.text.strip():
            chunks.append(part.text)
        elif part.kind == "grid":
            text = _row_text(part.cells)
            if text:
                chunks.append(text)
    return "\n\n".join(chunks)


def _coalesce(parts: list[Part]) -> list[Part]:
    out: list[Part] = []
    for part in parts:
        if part.kind == "text":
            text = clean(part.text)
            if not text:
                continue
            if out and out[-1].kind == "text":
                out[-1].text = clean(f"{out[-1].text}\n\n{text}")
            else:
                out.append(Part("text", text=text))
        else:
            out.append(part)
    return out


def html_to_reading(markup: str, base_url: str = "") -> list[Part]:
    parser = _Tree()
    parser.feed(markup)
    parser.close()
    article = _find(
        parser.root,
        lambda el: el.tag == "article" and "comment" not in _blob(el),
    )
    root = _content_root(parser.root)
    blocks: list[El | str] = []
    _walk_blocks(root, blocks)
    parts: list[Part] = []
    for block in blocks:
        parts.extend(_block_parts(block, base_url))
    title = ""
    if article is not None and not _find(root, lambda el: el.tag == "h1"):
        title = _first_h1(article)
    reading = _reading_text(parts)
    if title and (not reading or norm_heading(title) != norm_heading(reading.split("\n", 1)[0])):
        parts.insert(0, Part("text", text=title))
    return _coalesce(parts)


def plain_reading(text: str) -> str:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    return raw.strip()


def _has_letters(text: str) -> bool:
    return any(char.isalnum() for char in text)


def _text_result(reading: str, source: str) -> Result:
    parts = [Part("text", text=reading)] if reading else []
    return Result(ok=True, reading=reading, parts=parts, source=source)


@dataclass
class _Line:
    top: int
    left: int
    height: int
    text: str


@dataclass
class _Shot:
    top: int
    left: int
    width: int
    height: int
    path: Path


def _num(el: ET.Element, name: str) -> int:
    raw = el.get(name) or "0"
    try:
        return int(float(raw))
    except ValueError:
        return 0


def _lines(boxes: list[tuple[int, int, int, str]]) -> list[_Line]:
    ordered = sorted(boxes, key=lambda box: (box[0], box[1]))
    groups: list[list[tuple[int, int, int, str]]] = []
    for box in ordered:
        if groups and abs(box[0] - groups[-1][0][0]) <= LINE_SLACK:
            groups[-1].append(box)
        else:
            groups.append([box])
    lines: list[_Line] = []
    for group in groups:
        group.sort(key=lambda box: box[1])
        pieces = [re.sub(r"[ \t]+", " ", box[3]).strip() for box in group]
        text = " ".join(piece for piece in pieces if piece)
        if not text:
            continue
        lines.append(
            _Line(
                top=min(box[0] for box in group),
                left=min(box[1] for box in group),
                height=max(box[2] for box in group),
                text=text,
            )
        )
    return lines


def _bands(shots: list[_Shot]) -> list[list[_Shot]]:
    ordered = sorted(shots, key=lambda shot: (shot.top, shot.left))
    bands: list[list[_Shot]] = []
    for shot in ordered:
        if not bands:
            bands.append([shot])
            continue
        top = min(item.top for item in bands[-1])
        bottom = max(item.top + item.height for item in bands[-1])
        if shot.top <= bottom and shot.top + shot.height >= top:
            bands[-1].append(shot)
        else:
            bands.append([shot])
    for band in bands:
        band.sort(key=lambda shot: shot.left)
    return bands


def _label_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _is_label(text: str, width: int, height: int) -> bool:
    if not text or len(text) > LABEL_CHARS or len(text.split()) > LABEL_WORDS:
        return False
    return width <= LABEL_WIDTH and 0 < height <= 30


def _grids(
    texts: list[tuple[int, int, int, int, str]],
    shots: list[_Shot],
    page: int,
) -> tuple[list[Part], set[int], set[int]]:
    """A chart whose cells are images and whose row labels are short text."""
    labels: list[tuple[int, int, int, int, int, str]] = []
    for index, (top, left, width, height, text) in enumerate(texts):
        cleaned = _label_text(text)
        if _is_label(cleaned, width, height):
            labels.append((index, top, left, width, height, cleaned))
    labels.sort(key=lambda item: (item[1], item[2]))
    rows: list[list[tuple[int, int, int, int, int, str]]] = []
    for item in labels:
        if rows and abs(item[1] - rows[-1][0][1]) <= LINE_SLACK:
            rows[-1].append(item)
        else:
            rows.append([item])
    runs: list[list[list[tuple[int, int, int, int, int, str]]]] = []
    current: list[list[tuple[int, int, int, int, int, str]]] = []
    for row in rows:
        if not current or row[0][1] - current[-1][0][1] <= ROW_GAP:
            current.append(row)
        else:
            runs.append(current)
            current = [row]
    if current:
        runs.append(current)

    grids: list[Part] = []
    drop_text: set[int] = set()
    drop_shot: set[int] = set()
    for run in runs:
        if len(run) < MIN_GRID_ROWS:
            continue
        labs = [item for row in run for item in row]
        min_top = min(item[1] for item in labs)
        max_bottom = max(item[1] + item[4] for item in labs)
        min_left = min(item[2] for item in labs)
        max_right = max(item[2] + item[3] for item in labs)
        image_cells: list[tuple[int, Cell]] = []
        for shot_index, shot in enumerate(shots):
            if shot_index in drop_shot:
                continue
            overlaps_y = shot.top < max_bottom and shot.top + shot.height > min_top
            overlaps_x = (
                shot.left < max_right + GRID_GUTTER and shot.left + shot.width > min_left - GRID_GUTTER
            )
            if not overlaps_y or not overlaps_x:
                continue
            data = shot.path.read_bytes()
            if not data:
                continue
            image_cells.append(
                (
                    shot_index,
                    Cell(
                        kind="image",
                        data=data,
                        media_type=_media_type(data),
                        top=shot.top,
                        left=shot.left,
                        width=shot.width,
                        height=shot.height,
                        chart=_read_chart(data),
                    ),
                )
            )
        if not image_cells:
            continue
        cells: list[Cell] = []
        for index, top, left, width, height, text in labs:
            cells.append(Cell("text", text=text, top=top, left=left, width=width, height=height))
            drop_text.add(index)
        for shot_index, cell in image_cells:
            cells.append(cell)
            drop_shot.add(shot_index)
        g_top = min(cell.top for cell in cells)
        g_left = min(cell.left for cell in cells)
        g_right = max(cell.left + cell.width for cell in cells)
        g_bottom = max(cell.top + cell.height for cell in cells)
        grids.append(
            Part(
                kind="grid",
                page=page,
                top=g_top,
                left=g_left,
                width=g_right - g_left,
                height=g_bottom - g_top,
                cells=cells,
            )
        )
    return grids, drop_text, drop_shot


def _column_parts(lines: list[_Line], shots: list[_Shot], grids: list[Part], page: int) -> list[Part]:
    items: list[tuple[int, int, str, _Line | list[_Shot] | Part]] = []
    for line in lines:
        items.append((line.top, line.left, "text", line))
    for band in _bands(shots):
        top = min(shot.top for shot in band)
        left = min(shot.left for shot in band)
        items.append((top, left, "band", band))
    for grid in grids:
        items.append((grid.top or 0, grid.left or 0, "grid", grid))
    items.sort(key=lambda item: (item[0], item[1]))

    parts: list[Part] = []
    pending: list[_Line] = []

    def flush():
        if not pending:
            return
        paragraphs: list[str] = []
        current: list[str] = []
        previous: _Line | None = None
        for line in pending:
            if previous is not None and line.top - previous.top > PARAGRAPH_GAP:
                if current:
                    paragraphs.append("\n".join(current))
                    current = []
            current.append(line.text)
            previous = line
        if current:
            paragraphs.append("\n".join(current))
        text = clean("\n\n".join(paragraphs))
        if text:
            parts.append(Part("text", text=text))
        pending.clear()

    for _top, _left, kind, payload in items:
        if kind == "text" and isinstance(payload, _Line):
            pending.append(payload)
        elif kind == "grid" and isinstance(payload, Part):
            flush()
            parts.append(payload)
        elif isinstance(payload, list):
            flush()
            for shot in payload:
                data = shot.path.read_bytes()
                if not data:
                    continue
                parts.append(
                    Part(
                        kind="image",
                        data=data,
                        media_type=_media_type(data),
                        page=page,
                        top=shot.top,
                        left=shot.left,
                        width=shot.width,
                        height=shot.height,
                        chart=_read_chart(data),
                    )
                )
    flush()
    return parts


def _image_file(src: str, folder: Path) -> Path | None:
    if not src:
        return None
    path = Path(src)
    if not path.is_absolute():
        path = folder / path
    try:
        path = path.resolve()
    except OSError:
        return None
    root = folder.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def _parts_from_pdf_xml(root: ET.Element, folder: Path) -> list[Part]:
    parts: list[Part] = []
    seen: set[tuple[int, int, int]] = set()
    for page_el in root.findall("page"):
        page = _num(page_el, "number")
        mid = _num(page_el, "width") / 2
        texts: list[tuple[int, int, int, int, str]] = []
        shots: list[_Shot] = []
        for el in page_el:
            if el.tag == "text":
                text = "".join(el.itertext())
                if not text.strip():
                    continue
                top, left = _num(el, "top"), _num(el, "left")
                width = _num(el, "width")
                height = _num(el, "height") or 1
                texts.append((top, left, width, height, text))
            elif el.tag == "image":
                top, left = _num(el, "top"), _num(el, "left")
                width, height = _num(el, "width"), _num(el, "height")
                slot = (page, top, left)
                if slot in seen:
                    continue
                seen.add(slot)
                path = _image_file(el.get("src") or "", folder)
                if path is None:
                    continue
                shots.append(_Shot(top, left, width, height, path))
        columns = (
            (
                [box for box in texts if box[1] < mid],
                [shot for shot in shots if shot.left + shot.width / 2 < mid],
            ),
            (
                [box for box in texts if box[1] >= mid],
                [shot for shot in shots if shot.left + shot.width / 2 >= mid],
            ),
        )
        for column_texts, column_shots in columns:
            grids, drop_text, drop_shot = _grids(column_texts, column_shots, page)
            kept_text = [
                (top, left, height, text)
                for index, (top, left, _width, height, text) in enumerate(column_texts)
                if index not in drop_text
            ]
            kept_shots = [shot for index, shot in enumerate(column_shots) if index not in drop_shot]
            parts.extend(_column_parts(_lines(kept_text), kept_shots, grids, page))
    return parts


def _read_chart(data: bytes) -> dict | None:
    if not data:
        return None
    try:
        from pattern_import.chart import read_chart
    except ImportError:
        return None
    chart = read_chart(data)
    if chart is None:
        return None
    return chart.as_dict()


def _media_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    return "application/octet-stream"


def _pdf_parts(data: bytes) -> list[Part]:
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        pdf_path = folder / "pattern.pdf"
        pdf_path.write_bytes(data)
        xml_path = folder / "pattern.xml"
        subprocess.run(
            ["pdftohtml", "-xml", "-nodrm", "-q", str(pdf_path), str(xml_path)],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if not xml_path.is_file():
            return []
        root = ET.parse(xml_path).getroot()
        words = " ".join("".join(el.itertext()) for el in root.iter("text"))
        if not _has_letters(words):
            return []
        return _coalesce(_parts_from_pdf_xml(root, folder))


def from_pdf(data: bytes, source: str) -> Result:
    parts = _pdf_parts(data)
    reading = _reading_text(parts)
    if not _has_letters(reading):
        return Result(ok=False, code="empty-pdf", message=MSG_SCAN)
    return Result(ok=True, reading=reading, parts=parts, source=source)


def from_html(data: bytes, source: str, base_url: str = "") -> Result:
    markup = data.decode("utf-8-sig", errors="replace")
    parts = html_to_reading(markup, base_url)
    return Result(
        ok=True,
        reading=_reading_text(parts),
        parts=parts,
        source=source,
    )


def from_text(data: bytes, source: str) -> Result:
    return _text_result(plain_reading(data.decode("utf-8-sig", errors="replace")), source)


def source_from_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.hostname or ""
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return f"From {host}{path}"


def source_from_filename(filename: str) -> str:
    name = Path(filename).name or "file"
    return f"From {name}"


def _looks_like_html(data: bytes) -> bool:
    sample = data[:4096].lower()
    return any(token in sample for token in (b"<html", b"<body", b"<article", b"<p", b"<div"))


def _is_html_file(name: str, kind: str) -> bool:
    if name.endswith(".html") or name.endswith(".htm"):
        return True
    return kind in {"text/html", "application/xhtml+xml"}


def extract_bytes(data: bytes, filename: str, content_type: str) -> Result:
    """A file the knitter chose. HTML, PDF, and TXT."""
    name = filename.lower()
    kind = content_type.lower().split(";", 1)[0].strip()
    source = source_from_filename(filename)
    if data.startswith(b"%PDF") or name.endswith(".pdf") or kind == "application/pdf":
        return from_pdf(data, source)
    if name.endswith(".txt"):
        return from_text(data, source)
    if _is_html_file(name, kind):
        return from_html(data, source)
    if kind == "text/plain":
        return from_text(data, source)
    return Result(ok=False, code="type", message=MSG_FILE_TYPE)


def extract_fetched(data: bytes, content_type: str, source: str, base_url: str = "") -> Result:
    kind = content_type.lower()
    if data.startswith(b"%PDF") or "pdf" in kind:
        return from_pdf(data, source)
    if "html" in kind or _looks_like_html(data):
        return from_html(data, source, base_url)
    if kind.startswith("text/"):
        return from_text(data, source)
    return Result(ok=False, code="type", message=MSG_URL_TYPE)


def fetch_url(url: str) -> Result:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return Result(ok=False, code="fetch", message=MSG_FETCH)
    source = source_from_url(url)
    request = Request(url, headers={"User-Agent": "Cardigan"})
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT) as response:
            status = getattr(response, "status", 200)
            content_type = response.headers.get("Content-Type", "")
            data = response.read(MAX_BYTES + 1)
    except (URLError, TimeoutError, OSError, ValueError):
        return Result(ok=False, code="fetch", message=MSG_FETCH)
    if status >= 400 or len(data) > MAX_BYTES:
        return Result(ok=False, code="fetch", message=MSG_FETCH)
    return extract_fetched(data, content_type, source, url)
