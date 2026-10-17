"""Extraction against the saved sources. No invented pattern prose."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pattern_import.extract import (
    IMAGE_LINE,
    MSG_FETCH,
    MSG_FILE_TYPE,
    MSG_SCAN,
    MSG_URL_TYPE,
    extract_bytes,
    fetch_url,
    html_to_reading,
    source_from_url,
    split_text,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources"


def _read(relative: str) -> str:
    return (SOURCES / relative).read_text(encoding="utf-8")


class HtmlTests(unittest.TestCase):
    def test_creative_tien_keeps_the_instructions_and_drops_chrome(self):
        reading, abbreviations, images = html_to_reading(
            _read("patterns/creative-tien-lk150-tuck-blanket.html")
        )
        self.assertIsNone(abbreviations)
        self.assertTrue(images)
        self.assertIn(IMAGE_LINE, reading)
        self.assertIn("Tuck stitch blanket on an LK150", reading)
        self.assertIn("Change the Russell lever to I", reading)
        self.assertNotIn("Join our email newsletter", reading)
        self.assertNotIn("You May Also Like", reading)
        self.assertNotIn("Latest Posts", reading)
        self.assertNotIn("How to machine knit a heart shape", reading)
        self.assertNotIn("Leave a Reply", reading)

    def test_city_farmhouse_glossary_is_the_list(self):
        reading, abbreviations, images = html_to_reading(
            _read("patterns/city-farmhouse-wrap-sweater-scarf.html")
        )
        self.assertTrue(images)
        self.assertIn(IMAGE_LINE, reading)
        self.assertEqual(abbreviations, "RC = row count\nSts = stitches")
        self.assertNotIn("RC = row count", reading)
        self.assertIn("ewrap cast on", reading)
        self.assertIn("Machine Knit Wrap Sweater Scarf Pattern", reading)
        self.assertNotIn("Very nice and elegant", reading)
        self.assertNotIn("Polly", reading)

    def test_clearwater_long_heading_stays_in_the_reading(self):
        reading, abbreviations, images = html_to_reading(
            _read("references/clearwater-abbreviations.html")
        )
        self.assertIsNone(abbreviations)
        self.assertIn("Machine Knitting Abbreviations and Terms", reading)
        self.assertIn("alternate", reading)
        self.assertNotIn("Home", reading.split("Machine Knitting", 1)[0])


class PlainTests(unittest.TestCase):
    def test_paste_splits_a_glossary_heading_once(self):
        text = (
            "Machine Knit Wrap Sweater Scarf Pattern\n\n"
            "Glossary\n"
            "RC = row count\n"
            "Sts = stitches\n\n"
            "Notes\n"
            "Instructions are written for hand manipulation of the stitches in the body.\n"
        )
        result = split_text(text)
        self.assertTrue(result.ok)
        self.assertEqual(result.source, "Pasted")
        self.assertEqual(result.abbreviations, "RC = row count\nSts = stitches")
        self.assertIn("hand manipulation", result.reading)
        self.assertNotIn("RC = row count", result.reading)
        self.assertIn("Notes", result.reading)

    def test_paste_without_a_heading_is_the_reading(self):
        text = "Change the Russell lever to I, so the D-position needles will not be knitted."
        result = split_text(text)
        self.assertIsNone(result.abbreviations)
        self.assertEqual(result.reading, text)

    def test_txt_round_trip_and_refused_types(self):
        body = b"Knit 2 rows.\n"
        txt = extract_bytes(body, "rows.txt", "text/plain")
        self.assertTrue(txt.ok)
        self.assertEqual(txt.source, "From rows.txt")
        self.assertIn("Knit 2 rows.", txt.reading)
        refused = extract_bytes(b"<p>Knit 2 rows.</p>", "pattern.html", "text/html")
        self.assertFalse(refused.ok)
        self.assertEqual(refused.message, MSG_FILE_TYPE)
        png = extract_bytes(b"\x89PNG\r\n", "photo.png", "image/png")
        self.assertFalse(png.ok)
        self.assertEqual(png.message, MSG_FILE_TYPE)


class PdfTests(unittest.TestCase):
    def test_eileen_has_selectable_text_and_pictures(self):
        data = (SOURCES / "patterns/eileen-montgomery-lk150-fairisle.pdf").read_bytes()
        result = extract_bytes(data, "eileen-montgomery-lk150-fairisle.pdf", "application/pdf")
        self.assertTrue(result.ok, result.message)
        self.assertIn("LK150 Fairisle", result.reading)
        self.assertTrue(result.images_omitted)
        self.assertIn(IMAGE_LINE, result.reading)
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
            self.assertEqual(html.abbreviations, "RC = row count\nSts = stitches")
            self.assertIn("hand manipulation", html.reading)
            self.assertIn(IMAGE_LINE, html.reading)
            refused = fetch_url(f"http://127.0.0.1:{port}/photo.png")
            self.assertFalse(refused.ok)
            self.assertEqual(refused.message, MSG_URL_TYPE)
        finally:
            server.shutdown()
            server.server_close()


class ServerTests(unittest.TestCase):
    def test_page_and_split_route(self):
        from urllib.request import Request, urlopen

        from pattern_import.server import make_server

        server = make_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            page = urlopen(f"http://127.0.0.1:{port}/").read().decode()
            self.assertIn("Count this as the pattern", page)
            body = json.dumps({"text": "Glossary\nRC = row count\n\nKnit 2 rows.\n"}).encode()
            request = Request(
                f"http://127.0.0.1:{port}/split",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            payload = json.loads(urlopen(request).read())
            self.assertEqual(payload["abbreviations"], "RC = row count")
            self.assertIn("Knit 2 rows.", payload["reading"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
