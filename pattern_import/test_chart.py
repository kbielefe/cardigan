"""Chart images become color grids. The fairisle pages are the saved pattern."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import cv2
import numpy as np

from pattern_import.chart import (
    MSG_COLORS,
    MSG_GRID,
    MSG_IMAGE,
    MSG_SMALL,
    chart_from_image,
    main,
    read_chart,
)
from pattern_import.extract import extract_bytes

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources"
FAIRISLE = {
    (1, 92, 150): (
        8,
        6,
        (
            "WKKKKK",
            "GWWWWW",
            "GGWWWG",
            "WWKKKW",
            "WWWKWW",
            "GGGWGG",
            "WGGGGG",
            "KWWWWW",
        ),
    ),
    (1, 92, 68): (
        4,
        6,
        (
            "KKWWWK",
            "WWGGGW",
            "WWWGWW",
            "KKKWKK",
        ),
    ),
    (1, 91, 110): (
        6,
        6,
        (
            "GKKKKK",
            "GGKKKG",
            "GGGKGG",
            "KGGGGG",
            "KKGGGK",
            "KKKGKK",
        ),
    ),
    (2, 92, 150): (
        8,
        6,
        (
            "WWKWWW",
            "WKKKWW",
            "KKWKKW",
            "KWWWKK",
            "WWGWWK",
            "WGGGWW",
            "WWGWWK",
            "KWWWKK",
        ),
    ),
    (2, 92, 50): (
        3,
        6,
        (
            "KKWKKW",
            "WKKKWW",
            "WWKWWW",
        ),
    ),
    (2, 92, 92): (
        5,
        6,
        (
            "KWWWWW",
            "KKWWWW",
            "KKKWWW",
            "KKKKWW",
            "KKKKKW",
        ),
    ),
    (2, 32, 38): (
        2,
        2,
        (
            "WK",
            "KW",
        ),
    ),
}
STITCH = {"K": (0, 0, 0), "W": (255, 255, 255), "G": (153, 153, 153)}
RULE = (187, 187, 187)
_AA_STITCH = {"K": (6, 4, 8), "W": (248, 248, 246), "R": (230, 12, 46)}


def _rgb(hex_code: str) -> tuple[int, int, int]:
    return tuple(int(hex_code[index : index + 2], 16) for index in (1, 3, 5))


def _near(hex_code: str, color: tuple[int, int, int], limit: int = 8) -> bool:
    return all(abs(channel - target) <= limit for channel, target in zip(_rgb(hex_code), color, strict=True))


def _aa_chart(pattern: tuple[str, ...], *, frame: int = 6, extra_col: bool = False) -> np.ndarray:
    """A framed chart whose rules are thin, noisy gray instead of one flat color.

    ``extra_col`` adds one white square past the last vertical rule, then a
    thin border. That square is a stitch the rules do not enclose.
    """
    rows = len(pattern)
    cols = len(pattern[0])
    cell, rule = 11, 1
    pitch = cell + rule
    last_rule = frame + cols * pitch
    height = frame + rows * pitch + rule + frame
    width = last_rule + pitch + 2 if extra_col else last_rule + rule + frame
    rng = np.random.default_rng(2)
    image = np.empty((height, width, 3), dtype=np.int16)
    image[:] = (36, 32, 40)
    for _speck in range(80):
        image[rng.integers(0, height), rng.integers(0, width)] = rng.integers(0, 255, size=3)
    for row, line in enumerate(pattern):
        for col, symbol in enumerate(line):
            y0 = frame + rule + row * pitch
            x0 = frame + rule + col * pitch
            noise = rng.integers(-6, 7, size=(cell, cell, 3))
            image[y0 : y0 + cell, x0 : x0 + cell] = _AA_STITCH[symbol] + noise
        if extra_col:
            y0 = frame + rule + row * pitch
            x0 = last_rule + rule
            noise = rng.integers(-6, 7, size=(cell, cell, 3))
            image[y0 : y0 + cell, x0 : x0 + cell] = _AA_STITCH["W"] + noise
    for index in range(rows + 1):
        y = frame + index * pitch
        gray = rng.integers(140, 210, size=(width, 1))
        image[y, :, :] = gray
    for index in range(cols + 1):
        x = frame + index * pitch
        gray = rng.integers(140, 210, size=(height, 1))
        image[:, x, :] = gray
    return np.clip(image, 0, 255).astype(np.uint8)


def _png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("png")
    return encoded.tobytes()


class _Chart:
    def __init__(self, payload):
        self.grid = np.array(payload["grid"])
        self.colors = {int(index): color for index, color in payload["colors"].items()}


def _attached(result):
    found = {}
    for part in result.parts:
        if part.kind == "image" and part.data:
            found.setdefault((part.page, part.width, part.height), part)
        elif part.kind == "grid":
            for cell in part.cells:
                if cell.kind == "image" and cell.data:
                    found.setdefault((part.page, cell.width, cell.height), cell)
    return found


def _images(result):
    for part in result.parts:
        if part.kind == "image" and part.data:
            yield part.page, part.width, part.height, part.data
        elif part.kind == "grid":
            for cell in part.cells:
                if cell.kind == "image" and cell.data:
                    yield part.page, cell.width, cell.height, cell.data


class ChartTests(unittest.TestCase):
    def test_fairisle_charts_keep_their_squares(self):
        data = (SOURCES / "patterns/eileen-montgomery-lk150-fairisle.pdf").read_bytes()
        result = extract_bytes(data, "eileen-montgomery-lk150-fairisle.pdf", "application/pdf")
        self.assertTrue(result.ok, result.message)
        json.dumps(result.as_dict())
        found = {}
        for page, width, height, blob in _images(result):
            found.setdefault((page, width, height), blob)
        self.assertEqual(sorted(key for key in FAIRISLE if key not in found), [])
        for key, (rows, cols, pattern) in FAIRISLE.items():
            chart = read_chart(found[key])
            self.assertIsNotNone(chart)
            self.assertEqual(chart.grid.shape, (rows, cols))
            self._squares(chart, pattern)
        for key, blob in found.items():
            if key not in FAIRISLE:
                self.assertIsNone(read_chart(blob), key)
        attached = _attached(result)
        for key, (rows, cols, pattern) in FAIRISLE.items():
            item = attached[key]
            self.assertTrue(item.data)
            payload = item.as_dict()
            self.assertIn("src", payload)
            self.assertEqual(len(payload["chart"]["grid"]), rows)
            self.assertEqual(len(payload["chart"]["grid"][0]), cols)
            self._squares(_Chart(payload["chart"]), pattern)
        for key, item in attached.items():
            if key not in FAIRISLE:
                self.assertIsNone(item.chart, key)
                self.assertNotIn("chart", item.as_dict())

    def test_antialiased_rules_keep_the_squares(self):
        pattern = (
            "KWKWRWKW",
            "WKWKRKWK",
            "KKKKRKKK",
            "WWWWRWWW",
        )
        chart = read_chart(_aa_chart(pattern))
        self.assertIsNotNone(chart)
        self.assertEqual(chart.grid.shape, (4, 8))
        seen = {}
        for row, line in enumerate(pattern):
            for col, symbol in enumerate(line):
                color = chart.colors[int(chart.grid[row, col])]
                self.assertTrue(_near(color, _AA_STITCH[symbol], limit=24), color)
                seen.setdefault(symbol, color)
                self.assertTrue(_near(color, _rgb(seen[symbol]), limit=0))
        self.assertEqual(len(chart.colors), 3)
        for color in chart.colors.values():
            self.assertFalse(_near(color, (36, 32, 40), limit=16))
            self.assertFalse(_near(color, (170, 170, 170), limit=24))

    def test_a_thick_frame_and_a_short_mark_stay_with_the_squares(self):
        rows, cols = 10, 36
        marked = {1, 4, 8}
        mark = 17
        pattern = []
        for row in range(rows):
            symbols = ["K" if (row + col) % 2 == 0 else "W" for col in range(cols)]
            symbols[mark] = "R" if row in marked else "K"
            pattern.append("".join(symbols))
        chart = read_chart(_aa_chart(tuple(pattern), frame=10, extra_col=True))
        self.assertIsNotNone(chart)
        self.assertEqual(chart.grid.shape, (rows, cols + 1))
        seen = {}
        for row, line in enumerate(pattern):
            for col, symbol in enumerate(line):
                color = chart.colors[int(chart.grid[row, col])]
                self.assertTrue(_near(color, _AA_STITCH[symbol], limit=24), (row, col, color))
                seen.setdefault(symbol, color)
                self.assertTrue(_near(color, _rgb(seen[symbol]), limit=0))
        for row in range(rows):
            color = chart.colors[int(chart.grid[row, cols])]
            self.assertTrue(_near(color, _AA_STITCH["W"], limit=24), color)
        self.assertEqual(len(chart.colors), 3)
        self.assertEqual(len(seen), 3)
        for color in chart.colors.values():
            self.assertFalse(_near(color, (36, 32, 40), limit=16))
            self.assertFalse(_near(color, (170, 170, 170), limit=24))

    def test_a_wash_is_not_a_chart(self):
        image = np.zeros((90, 140, 3), dtype=np.uint8)
        image[:, :, 0] = np.linspace(20, 220, 140, dtype=np.uint8)
        image[:, :, 1] = 180
        image[:, :, 2] = 160
        self.assertIsNone(read_chart(image))

    def test_rules_between_squares_are_not_a_color(self):
        cell = 18
        rule = 6
        rows = ("KW", "WG")
        span = cell + rule
        size = rule + 2 * span
        image = np.full((size, size, 3), RULE, dtype=np.uint8)
        fills = {"K": (0, 0, 0), "W": (255, 255, 255), "G": (153, 153, 153)}
        for row, line in enumerate(rows):
            for col, symbol in enumerate(line):
                y0 = rule + row * span
                x0 = rule + col * span
                image[y0 : y0 + cell, x0 : x0 + cell] = fills[symbol]
        chart = read_chart(_png(image))
        self.assertIsNotNone(chart)
        self.assertEqual(chart.grid.shape, (2, 2))
        self._squares(chart, rows)
        for color in chart.colors.values():
            self.assertFalse(_near(color, RULE, limit=16))

    def test_noisy_squares_fall_back_to_two_colors(self):
        rng = np.random.default_rng(0)
        rows, cols = 4, 5
        image = np.zeros((rows * 2, cols * 2, 3), dtype=np.uint8)
        pattern = []
        for row in range(rows):
            line = []
            for col in range(cols):
                dark = (row + col) % 2 == 0
                base = 0 if dark else 255
                noise = rng.integers(-50, 51, size=3)
                image[row * 2 : (row + 1) * 2, col * 2 : (col + 1) * 2] = np.clip(base + noise, 0, 255)
                line.append("K" if dark else "W")
            pattern.append("".join(line))
        chart = chart_from_image(image, rows, cols, max_k=6)
        self.assertEqual(chart.grid.shape, (rows, cols))
        self.assertEqual(len(chart.colors), 2)
        dark = chart.colors[int(chart.grid[0, 0])]
        light = chart.colors[int(chart.grid[0, 1])]
        self.assertLess(sum(_rgb(dark)), sum(_rgb(light)))
        for row, line in enumerate(pattern):
            for col, symbol in enumerate(line):
                color = chart.colors[int(chart.grid[row, col])]
                self.assertEqual(color, dark if symbol == "K" else light)

    def test_max_k_caps_the_palette(self):
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        image[0:2, 0:2] = (0, 0, 0)
        image[0:2, 2:4] = (255, 0, 0)
        image[2:4, 0:2] = (0, 255, 0)
        image[2:4, 2:4] = (0, 0, 255)
        chart = chart_from_image(image, 2, 2, max_k=3)
        self.assertLessEqual(len(chart.colors), 3)
        self.assertGreaterEqual(len(chart.colors), 2)

    def test_one_color_is_a_blank_grid(self):
        image = np.full((6, 8, 3), 255, dtype=np.uint8)
        chart = chart_from_image(image, 3, 4)
        self.assertEqual(chart.grid.tolist(), [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])
        self.assertEqual(chart.colors, {0: "#FFFFFF"})

    def test_path_round_trip_prints_the_grid(self):
        image = np.zeros((4, 6, 3), dtype=np.uint8)
        image[:, 3:] = (255, 255, 255)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.png"
            path.write_bytes(_png(image))
            chart = chart_from_image(path, 2, 2)
            self.assertEqual(chart.grid.tolist(), [[0, 1], [0, 1]])
            output = StringIO()
            with redirect_stdout(output):
                code = main([str(path), "2", "2"])
        self.assertEqual(code, 0)
        lines = output.getvalue().strip().splitlines()
        self.assertEqual(lines[0], "0 1")
        self.assertEqual(lines[1], "0 1")
        self.assertEqual(lines[3:], ["0 #000000", "1 #FFFFFF"])

    def test_bad_inputs_fail_in_words(self):
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        for args in ((image, 0, 2), (image, 2, -1), (image, True, 2)):
            with self.assertRaises(ValueError) as caught:
                chart_from_image(*args)
            self.assertEqual(str(caught.exception), MSG_GRID)
        with self.assertRaises(ValueError) as caught:
            chart_from_image(image, 2, 2, max_k=1)
        self.assertEqual(str(caught.exception), MSG_COLORS)
        with self.assertRaises(ValueError) as caught:
            chart_from_image(b"not a picture", 2, 2)
        self.assertEqual(str(caught.exception), MSG_IMAGE)
        with self.assertRaises(ValueError) as caught:
            chart_from_image(image, 8, 2)
        self.assertEqual(str(caught.exception), MSG_SMALL)
        self.assertEqual(main(["/no/such/chart.png", "2", "2"]), 1)

    def _squares(self, chart, pattern):
        symbols = set("".join(pattern))
        self.assertEqual(chart.grid.shape, (len(pattern), len(pattern[0])))
        self.assertEqual(len(chart.colors), len(symbols))
        seen = {}
        for row, line in enumerate(pattern):
            for col, symbol in enumerate(line):
                index = int(chart.grid[row, col])
                color = chart.colors[index]
                self.assertTrue(_near(color, STITCH[symbol]), color)
                for other in symbols - {symbol}:
                    self.assertFalse(_near(color, STITCH[other]))
                seen.setdefault(symbol, index)
                self.assertEqual(index, seen[symbol])
        for color in chart.colors.values():
            self.assertFalse(_near(color, RULE, limit=16))


if __name__ == "__main__":
    unittest.main()
