"""Extraction against the saved sources. No invented pattern prose."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pattern_import.extract import (
    MSG_FETCH,
    MSG_FILE_TYPE,
    MSG_SCAN,
    MSG_URL_TYPE,
    extract_bytes,
    fetch_url,
    html_to_reading,
    source_from_url,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources"


def _read(relative: str) -> str:
    return (SOURCES / relative).read_text(encoding="utf-8")


def _words(parts) -> str:
    return "\n\n".join(part.text for part in parts if part.kind == "text")


def _images(parts):
    return [part for part in parts if part.kind == "image"]


class HtmlTests(unittest.TestCase):
    def test_creative_tien_keeps_the_instructions_and_drops_chrome(self):
        parts = html_to_reading(_read("patterns/creative-tien-lk150-tuck-blanket.html"))
        reading = _words(parts)
        srcs = [part.src for part in _images(parts)]
        self.assertTrue(any("baby-blanket" in src for src in srcs))
        self.assertNotIn("left out", reading)
        self.assertIn("Tuck stitch blanket on an LK150", reading)
        self.assertIn("Change the Russell lever to I", reading)
        self.assertNotIn("Join our email newsletter", reading)
        self.assertNotIn("You May Also Like", reading)
        self.assertNotIn("Latest Posts", reading)
        self.assertNotIn("How to machine knit a heart shape", reading)
        self.assertNotIn("Leave a Reply", reading)

    def test_city_farmhouse_glossary_stays_in_the_reading(self):
        parts = html_to_reading(_read("patterns/city-farmhouse-wrap-sweater-scarf.html"))
        reading = _words(parts)
        srcs = [part.src for part in _images(parts)]
        self.assertTrue(srcs)
        self.assertTrue(any(src.startswith("https://") for src in srcs))
        self.assertNotIn("left out", reading)
        self.assertIn("Glossary", reading)
        self.assertIn("RC = row count", reading)
        self.assertIn("Sts = stitches", reading)
        self.assertIn("ewrap cast on", reading)
        self.assertIn("Machine Knit Wrap Sweater Scarf Pattern", reading)
        self.assertNotIn("Very nice and elegant", reading)
        self.assertNotIn("Polly", reading)

    def test_clearwater_long_heading_stays_in_the_reading(self):
        reading = _words(html_to_reading(_read("references/clearwater-abbreviations.html")))
        self.assertIn("Machine Knitting Abbreviations and Terms", reading)
        self.assertIn("alternate", reading)
        self.assertNotIn("Home", reading.split("Machine Knitting", 1)[0])


class PlainTests(unittest.TestCase):
    def test_txt_keeps_a_glossary_in_the_reading(self):
        text = (
            "Machine Knit Wrap Sweater Scarf Pattern\n\n"
            "Glossary\n"
            "RC = row count\n"
            "Sts = stitches\n\n"
            "Notes\n"
            "Instructions are written for hand manipulation of the stitches in the body.\n"
        )
        result = extract_bytes(text.encode(), "wrap.txt", "text/plain")
        self.assertTrue(result.ok)
        self.assertEqual(result.source, "From wrap.txt")
        self.assertNotIn("abbreviations", result.as_dict())
        self.assertIn("Glossary", result.reading)
        self.assertIn("RC = row count", result.reading)
        self.assertIn("Sts = stitches", result.reading)
        self.assertIn("hand manipulation", result.reading)
        self.assertIn("Notes", result.reading)

    def test_txt_without_a_heading_is_the_reading(self):
        text = "Change the Russell lever to I, so the D-position needles will not be knitted."
        result = extract_bytes(text.encode(), "lever.txt", "text/plain")
        self.assertEqual(result.reading, text)
        self.assertEqual(result.source, "From lever.txt")

    def test_txt_round_trip_and_refused_types(self):
        body = b"Knit 2 rows.\n"
        txt = extract_bytes(body, "rows.txt", "text/plain")
        self.assertTrue(txt.ok)
        self.assertEqual(txt.source, "From rows.txt")
        self.assertIn("Knit 2 rows.", txt.reading)
        html = extract_bytes(b"<p>Knit 2 rows.</p>", "pattern.html", "text/html")
        self.assertTrue(html.ok, html.message)
        self.assertEqual(html.source, "From pattern.html")
        self.assertIn("Knit 2 rows.", html.reading)
        self.assertNotIn("<p>", html.reading)
        htm = extract_bytes(b"<h1>Cast on</h1>", "notes.htm", "application/octet-stream")
        self.assertTrue(htm.ok, htm.message)
        self.assertIn("Cast on", htm.reading)
        typed = extract_bytes(b"<p>Tension 8.</p>", "saved", "text/html; charset=utf-8")
        self.assertTrue(typed.ok, typed.message)
        self.assertIn("Tension 8.", typed.reading)
        tagged = extract_bytes(b"<p>Knit 2 rows.</p>", "rows.txt", "text/html")
        self.assertEqual(tagged.reading, "<p>Knit 2 rows.</p>")
        png = extract_bytes(b"\x89PNG\r\n", "photo.png", "image/png")
        self.assertFalse(png.ok)
        self.assertEqual(png.message, MSG_FILE_TYPE)

    def test_sample_html_files(self):
        samples = (
            ("patterns/creative-tien-lk150-tuck-blanket.html", "Change the Russell lever to I"),
            ("patterns/city-farmhouse-wrap-sweater-scarf.html", "RC = row count"),
            ("patterns/clearwater-lk150-fairisle-method-1.html", "Both Side Levers"),
        )
        for relative, phrase in samples:
            data = (SOURCES / relative).read_bytes()
            name = Path(relative).name
            uploaded = extract_bytes(data, name, "text/html")
            direct = html_to_reading(data.decode("utf-8-sig", errors="replace"))
            self.assertTrue(uploaded.ok, uploaded.message)
            self.assertEqual(uploaded.source, f"From {name}")
            self.assertEqual(
                [(part.kind, part.text, part.src) for part in uploaded.parts],
                [(part.kind, part.text, part.src) for part in direct],
            )
            self.assertIn(phrase, uploaded.reading)
            self.assertNotIn("Join our email newsletter", uploaded.reading)
            self.assertNotIn("left out", uploaded.reading)


class PdfTests(unittest.TestCase):
    def test_eileen_has_selectable_text_and_pictures(self):
        data = (SOURCES / "patterns/eileen-montgomery-lk150-fairisle.pdf").read_bytes()
        result = extract_bytes(data, "eileen-montgomery-lk150-fairisle.pdf", "application/pdf")
        self.assertTrue(result.ok, result.message)
        self.assertIn("LK150 Fairisle", result.reading)
        self.assertIn("Manual Method", result.reading)
        self.assertNotIn("left out", result.reading)
        self.assertNotIn("imagesOmitted", result.as_dict())
        self.assertTrue(any("12" in line and "MC" in line for line in result.reading.splitlines()))
        grids = [part for part in result.parts if part.kind == "grid"]
        self.assertEqual([part.page for part in grids], [1])
        grid = grids[0]
        labels = [cell for cell in grid.cells if cell.kind == "text"]
        cells = [cell for cell in grid.cells if cell.kind == "image"]
        label_text = " ".join(cell.text for cell in labels)
        self.assertNotIn("Manual Method", label_text)
        self.assertNotIn("Studio Method", label_text)
        rc12 = next(cell for cell in labels if cell.text == "12")
        rc = [
            next(cell for cell in labels if cell.text == str(number) and abs(cell.left - rc12.left) <= 4)
            for number in range(12, 0, -1)
        ]
        self.assertTrue(all(rc[index].top < rc[index + 1].top for index in range(len(rc) - 1)))
        for cell in rc:
            color = next(
                item
                for item in labels
                if item.text in {"MC", "CC"} and abs(item.top - cell.top) <= 8 and item.left > cell.left
            )
            self.assertGreater(color.left, cell.left)
        stitch = [item for item in cells if item.width >= 80 and item.left < rc12.left]
        self.assertGreaterEqual(len(stitch), 1)
        pattern_edge = min(item.left for item in stitch)
        pattern = [
            next(cell for cell in labels if cell.text == str(number) and cell.left < pattern_edge)
            for number in range(6, 0, -1)
        ]
        for index, cell in enumerate(pattern):
            self.assertLessEqual(abs(cell.top - rc[2 * index + 1].top), 8)
        rc_top = rc[0].top
        rc_bottom = rc[-1].top + rc[-1].height
        for item in stitch:
            self.assertLess(item.top, rc_bottom)
            self.assertGreater(item.top + item.height, rc_top)
        arrow = next(item for item in cells if item.width < 30 and item.height > 100)
        self.assertLess(arrow.top, rc_bottom)
        self.assertGreater(arrow.top + arrow.height, rc_top)
        line = next(cell for cell in labels if cell.text == "Line")
        self.assertGreater(line.top, rc[-1].top)
        left_edge = max(item.left + item.width for item in stitch)
        right = [
            next(cell for cell in labels if cell.text == str(number) and cell.left > left_edge)
            for number in range(6, 0, -1)
        ]
        self.assertTrue(all(right[index].top < right[index + 1].top for index in range(len(right) - 1)))
        pictures = _images(result.parts)
        self.assertFalse(any(part.page == 1 and (part.left or 0) < 400 for part in pictures))
        self.assertTrue(any(part.page == 3 and (part.width or 0) >= 300 for part in pictures))
        prose = "\n".join(part.text for part in result.parts if part.kind == "text")
        self.assertIn("Manual Method", prose)
        self.assertIn("Studio Method", prose)
        self.assertIn("1. Manual Method", prose)
        self.assertIn("2. Studio Method", prose)
        self.assertTrue(any(part.kind == "text" and "1x1" in part.text for part in result.parts))
        self.assertEqual(sum(1 for part in pictures if part.page == 1 and part.left == 817), 1)
        self.assertEqual(result.source, "From eileen-montgomery-lk150-fairisle.pdf")

    def test_lk150_scan_has_no_text_layer(self):
        data = (SOURCES / "manuals/Silver Reed LK-150 Knitting Machine.pdf").read_bytes()
        result = extract_bytes(data, "Silver Reed LK-150 Knitting Machine.pdf", "application/pdf")
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "empty-pdf")
        self.assertEqual(result.message, MSG_SCAN)
        self.assertEqual(result.reading, "")


class FetchTests(unittest.TestCase):
    def test_source_line_is_host_and_path(self):
        self.assertEqual(
            source_from_url("https://creativetien.com/tuck-stitch-blanket-on-an-lk150-part-1/"),
            "From creativetien.com/tuck-stitch-blanket-on-an-lk150-part-1/",
        )

    def test_failed_fetch(self):
        result = fetch_url("http://127.0.0.1:9/")
        self.assertFalse(result.ok)
        self.assertEqual(result.message, MSG_FETCH)

    def test_fetched_pdf_and_refused_type(self):
        pdf = (SOURCES / "patterns/eileen-montgomery-lk150-fairisle.pdf").read_bytes()
        page = (
            "<!DOCTYPE html><html><body><article><div class='entry-content'>"
            "<h1>Machine Knit Wrap Sweater Scarf Pattern</h1>"
            "<p><strong>Glossary</strong><br>RC = row count<br>Sts = stitches</p>"
            "<p><strong>Notes</strong><br>Instructions are written for hand manipulation of the stitches in the body.</p>"
            "<img src='coat.jpg'>"
            "</div></article></body></html>"
        ).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/pattern.pdf"):
                    body, kind = pdf, "application/octet-stream"
                elif self.path.startswith("/pattern.html"):
                    body, kind = page, "text/html; charset=utf-8"
                else:
                    body, kind = b"\x89PNG", "image/png"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            fetched = fetch_url(f"http://127.0.0.1:{port}/pattern.pdf")
            self.assertTrue(fetched.ok, fetched.message)
            self.assertIn("LK150 Fairisle", fetched.reading)
            self.assertEqual(fetched.source, f"From 127.0.0.1:{port}/pattern.pdf")
            html = fetch_url(f"http://127.0.0.1:{port}/pattern.html")
            self.assertTrue(html.ok, html.message)
            self.assertNotIn("abbreviations", html.as_dict())
            self.assertIn("Glossary", html.reading)
            self.assertIn("RC = row count", html.reading)
            self.assertIn("Sts = stitches", html.reading)
            self.assertIn("hand manipulation", html.reading)
            self.assertNotIn("left out", html.reading)
            srcs = [part["src"] for part in html.as_dict()["parts"] if part["kind"] == "image"]
            self.assertIn(f"http://127.0.0.1:{port}/coat.jpg", srcs)
            refused = fetch_url(f"http://127.0.0.1:{port}/photo.png")
            self.assertFalse(refused.ok)
            self.assertEqual(refused.message, MSG_URL_TYPE)
        finally:
            server.shutdown()
            server.server_close()


class ServerTests(unittest.TestCase):
    def test_page_has_the_reading_and_no_abbreviations_box(self):
        from pattern_import.server import make_server

        server = make_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            page = urlopen(f"http://127.0.0.1:{port}/").read().decode()
            self.assertIn("Accept this input", page)
            self.assertNotIn("Count this as the pattern", page)
            self.assertIn("Paste the pattern.", page)
            self.assertIn("HTML, PDF, or TXT", page)
            self.assertIn("Choose an HTML, PDF, or TXT file", page)
            self.assertIn(".html", page)
            self.assertNotIn("abbr-list", page)
            self.assertNotIn(">Abbreviations<", page)
            sample = (SOURCES / "patterns/clearwater-lk150-fairisle-method-1.html").read_bytes()
            html_file = Request(
                f"http://127.0.0.1:{port}/file",
                data=sample,
                headers={
                    "Content-Type": "text/html",
                    "X-Filename": "clearwater-lk150-fairisle-method-1.html",
                },
            )
            html_payload = json.loads(urlopen(html_file).read())
            self.assertTrue(html_payload["ok"], html_payload)
            self.assertEqual(
                html_payload["source"],
                "From clearwater-lk150-fairisle-method-1.html",
            )
            self.assertIn("Both Side Levers", html_payload["reading"])
            self.assertNotIn("left out", html_payload["reading"])
            body = b"Glossary\nRC = row count\n\nKnit 2 rows.\n"
            request = Request(
                f"http://127.0.0.1:{port}/file",
                data=body,
                headers={"Content-Type": "text/plain", "X-Filename": "rows.txt"},
            )
            payload = json.loads(urlopen(request).read())
            self.assertNotIn("abbreviations", payload)
            self.assertNotIn("imagesOmitted", payload)
            self.assertEqual(payload["parts"], [{"kind": "text", "text": payload["reading"]}])
            self.assertIn("RC = row count", payload["reading"])
            self.assertIn("Knit 2 rows.", payload["reading"])
            split = Request(
                f"http://127.0.0.1:{port}/split",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as caught:
                urlopen(split)
            self.assertEqual(caught.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
