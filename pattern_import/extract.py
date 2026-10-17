"""Turn a paste, a page, a PDF, or a TXT file into the pattern's words.

The glossary is split out only when those words already carry a heading
Abbreviations, Abbreviation, or Glossary. Nothing here is resolved into passes.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

NONE_SENTENCE = (
    "None on this page. A list in the pattern would sit here. "
    "Cardigan does not add one."
)
IMAGE_LINE = "Pictures on this page were left out."
MSG_FETCH = "This address did not come back. Check it, or paste the pattern."
MSG_URL_TYPE = "Cardigan takes a page, a PDF, or a TXT file."
MSG_FILE_TYPE = "Cardigan takes a PDF or a TXT file."
MSG_SCAN = (
    "This PDF has no selectable text. Cardigan does not read a scan. "
    "Paste the pattern."
)

MAX_BYTES = 20 * 1024 * 1024
FETCH_TIMEOUT = 20
GLOSSARY = {"abbreviations", "abbreviation", "glossary"}
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
    "figure",
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
DEF_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9./+]*\s*(?:=|–|—|-|:)\s+\S")


@dataclass
class Result:
    ok: bool
    reading: str = ""
    abbreviations: str | None = None
    images_omitted: bool = False
    source: str = ""
    code: str = ""
    message: str = ""

    def as_dict(self) -> dict:
        if not self.ok:
            return {"ok": False, "code": self.code, "message": self.message}
        return {
            "ok": True,
            "reading": self.reading,
            "abbreviations": self.abbreviations,
            "imagesOmitted": self.images_omitted,
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
        elif chrome and _chrome(child):
            continue
        else:
            parts.append(_text(child, chrome))
    return "".join(parts)


def _has_block(el: El) -> bool:
    for child in el.children:
        if not isinstance(child, El) or _chrome(child):
            continue
        if child.tag in BLOCK_TAGS or _has_block(child):
            return True
    return False


def _walk_blocks(el: El, out: list[El]):
    if _chrome(el):
        return
    if el.tag in BLOCK_TAGS:
        out.append(el)
        return
    if _has_block(el):
        for child in el.children:
            if isinstance(child, El):
                _walk_blocks(child, out)
        return
    if clean(_text(el)):
        out.append(el)


def _section_label(el: El) -> tuple[str | None, str]:
    """A heading label and the rest of the block, or the whole block as body."""
    full = clean(_text(el))
    if el.tag in HEADING_TAGS:
        return full, ""
    nodes = [child for child in el.children if not (isinstance(child, str) and not child.strip())]
    if nodes and isinstance(nodes[0], El) and nodes[0].tag in {"strong", "b"}:
        label = clean(_text(nodes[0]))
        nxt = nodes[1] if len(nodes) > 1 else None
        followed_by_break = isinstance(nxt, El) and nxt.tag == "br"
        if norm_heading(label) in GLOSSARY or (followed_by_break and len(label) <= 60 and "." not in label):
            rest = clean(_render(nodes[2:] if followed_by_break else nodes[1:]))
            return label, rest
    if "\n" not in full and norm_heading(full) in GLOSSARY:
        return full, ""
    return None, full


def _render(nodes: list[El | str]) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            parts.append(node)
        elif node.tag == "br":
            parts.append("\n")
        elif node.tag == "img" or _chrome(node):
            continue
        else:
            parts.append(_text(node))
    return "".join(parts)


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


def _count_images(el: El) -> int:
    count = 1 if el.tag == "img" else 0
    for child in el.children:
        if isinstance(child, El) and child.tag not in {"script", "style"}:
            count += _count_images(child)
    return count


def html_to_reading(markup: str) -> tuple[str, str | None, bool]:
    parser = _Tree()
    parser.feed(markup)
    parser.close()
    article = _find(
        parser.root,
        lambda el: el.tag == "article" and "comment" not in _blob(el),
    )
    root = _content_root(parser.root)
    images = _count_images(root) > 0
    blocks = []
    _walk_blocks(root, blocks)

    sections: list[tuple[str | None, list[str]]] = []
    current: tuple[str | None, list[str]] = (None, [])

    def push(label: str | None = None):
        nonlocal current
        if current[0] is not None or current[1]:
            sections.append(current)
        current = (label, [])

    for block in blocks:
        label, rest = _section_label(block)
        if label is not None:
            push(label)
            if rest:
                current[1].extend(line for line in rest.split("\n") if line.strip())
        elif rest:
            current[1].extend(line for line in rest.split("\n") if line.strip())
    push()

    reading_parts: list[str] = []
    abbreviations: str | None = None
    for label, lines in sections:
        if label is not None and norm_heading(label) in GLOSSARY and abbreviations is None:
            abbreviations = "\n".join(lines).strip()
            continue
        if label:
            reading_parts.append(label)
        reading_parts.extend(lines)

    title = ""
    if article is not None and not _find(root, lambda el: el.tag == "h1"):
        title = _first_h1(article)
    reading = "\n\n".join(part for part in reading_parts if part.strip())
    if title and norm_heading(title) != norm_heading(reading.split("\n", 1)[0]):
        reading = f"{title}\n\n{reading}" if reading else title
    if images and reading:
        reading = f"{reading.rstrip()}\n\n{IMAGE_LINE}"
    return reading.strip(), abbreviations, images


def split_plain(text: str) -> tuple[str, str | None]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    lines = raw.split("\n")
    heading_at = None
    for index, line in enumerate(lines):
        if norm_heading(line) in GLOSSARY:
            heading_at = index
            break
    if heading_at is None:
        return raw.strip(), None

    before = lines[:heading_at]
    after = lines[heading_at + 1 :]
    abbreviation_lines: list[str] = []
    rest_at = 0
    saw_blank = False
    for index, line in enumerate(after):
        stripped = re.sub(r"[ \t]+", " ", line).strip()
        if stripped == "":
            saw_blank = True
            continue
        if DEF_LINE.match(stripped) or (abbreviation_lines and not saw_blank):
            abbreviation_lines.append(stripped)
            saw_blank = False
            rest_at = index + 1
            continue
        rest_at = index
        break
    else:
        rest_at = len(after)

    reading = "\n".join(before + after[rest_at:])
    reading = re.sub(r"\n{3,}", "\n\n", reading).strip()
    return reading, "\n".join(abbreviation_lines).strip()


def _has_letters(text: str) -> bool:
    return any(char.isalnum() for char in text)


def _pdf_parts(data: bytes) -> tuple[str, bool]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "pattern.pdf"
        path.write_bytes(data)
        text_proc = subprocess.run(
            ["pdftotext", "-q", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            timeout=60,
            check=False,
        )
        image_proc = subprocess.run(
            ["pdfimages", "-list", str(path)],
            capture_output=True,
            timeout=60,
            check=False,
        )
    text = text_proc.stdout.decode("utf-8", errors="replace")
    images = any(
        re.match(r"\s*\d+\s+\d+\s+image\b", line)
        for line in image_proc.stdout.decode("utf-8", errors="replace").splitlines()
    )
    return text, images


def from_pdf(data: bytes, source: str) -> Result:
    text, images = _pdf_parts(data)
    if not _has_letters(text):
        return Result(ok=False, code="empty-pdf", message=MSG_SCAN)
    reading, abbreviations = split_plain(text)
    if images and reading:
        reading = f"{reading.rstrip()}\n\n{IMAGE_LINE}"
    return Result(
        ok=True,
        reading=reading,
        abbreviations=abbreviations,
        images_omitted=images,
        source=source,
    )


def from_html(data: bytes, source: str) -> Result:
    markup = data.decode("utf-8-sig", errors="replace")
    reading, abbreviations, images = html_to_reading(markup)
    return Result(
        ok=True,
        reading=reading,
        abbreviations=abbreviations,
        images_omitted=images,
        source=source,
    )


def from_text(data: bytes, source: str) -> Result:
    text = data.decode("utf-8-sig", errors="replace")
    reading, abbreviations = split_plain(text)
    return Result(ok=True, reading=reading, abbreviations=abbreviations, source=source)


def split_text(text: str) -> Result:
    reading, abbreviations = split_plain(text)
    return Result(ok=True, reading=reading, abbreviations=abbreviations, source="Pasted")


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


def extract_bytes(data: bytes, filename: str, content_type: str) -> Result:
    """A file the knitter chose. PDF and TXT only."""
    name = filename.lower()
    kind = content_type.lower().split(";", 1)[0].strip()
    source = source_from_filename(filename)
    if data.startswith(b"%PDF") or name.endswith(".pdf") or kind == "application/pdf":
        return from_pdf(data, source)
    if name.endswith(".txt") or kind == "text/plain":
        return from_text(data, source)
    return Result(ok=False, code="type", message=MSG_FILE_TYPE)


def extract_fetched(data: bytes, content_type: str, source: str) -> Result:
    kind = content_type.lower()
    if data.startswith(b"%PDF") or "pdf" in kind:
        return from_pdf(data, source)
    if "html" in kind or _looks_like_html(data):
        return from_html(data, source)
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
    return extract_fetched(data, content_type, source)
