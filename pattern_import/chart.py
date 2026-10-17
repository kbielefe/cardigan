"""Turn a knitting chart image into the color of each square.

The grid keeps the picture's row order, top to bottom. A fairisle chart is
read from the bottom when the passes are made. That reading comes later.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

BIN = 8
NOISE = 0.01
SAMPLE_LIMIT = 2000

MSG_IMAGE = "Cardigan could not read this chart image."
MSG_GRID = "A chart needs at least one row and one column."
MSG_COLORS = "A chart looks for at least two colors."
MSG_SMALL = "This chart image is smaller than the grid."


@dataclass(frozen=True)
class Chart:
    """Color indices for each square, and the hex color of each index."""

    grid: np.ndarray
    colors: dict[int, str]

    def as_dict(self) -> dict:
        return {
            "grid": self.grid.astype(int).tolist(),
            "colors": {str(index): color for index, color in self.colors.items()},
        }


def chart_from_image(
    image: str | Path | bytes | np.ndarray,
    num_rows: int,
    num_cols: int,
    max_k: int = 6,
) -> Chart:
    """Read a chart image as a grid of color indices.

    ``num_rows`` and ``num_cols`` are the squares in the picture, not the
    rules between them. ``max_k`` is the most colors to look for.

    A clean chart uses its own colors. The color of a square is the median
    of its center, so the rules and specks stay out. A color that fills
    less than 1% of those centers is left out. When the rest is between
    two and ``max_k``, that palette is the chart. When the centers are
    still messy, k-means tries each count up to ``max_k`` and keeps the
    grouping with the best silhouette.

    The grid is row-major from the top of the image. ``colors`` maps each
    index to a hex code.
    """
    rows = _count(num_rows, MSG_GRID)
    cols = _count(num_cols, MSG_GRID)
    limit = _count(max_k, MSG_COLORS)
    if limit < 2:
        raise ValueError(MSG_COLORS)
    rgb = _load_rgb(image)
    samples = _cell_colors(rgb, rows, cols)
    palette = _palette(samples.reshape(-1, 3), limit)
    grid = _indices(samples, palette)
    colors = {index: _hex(color) for index, color in enumerate(palette)}
    return Chart(grid=grid, colors=colors)


def chart_size(image: str | Path | bytes | np.ndarray) -> tuple[int, int] | None:
    """Rows and columns when the rules between squares line up.

    A photograph, a logo, or a mark that is not a grid of squares is None.
    The count lets the page read a chart the knitter did not measure.
    """
    try:
        rgb = _load_rgb(image)
    except ValueError:
        return None
    quantized = _quantize(rgb.reshape(-1, 3)).reshape(rgb.shape)
    flat = quantized.reshape(-1, 3)
    if len(flat) > 4000:
        flat = flat[:: max(1, len(flat) // 4000)]
    if len(np.unique(flat, axis=0)) > 16:
        return None
    height, width = quantized.shape[:2]
    row_colors = [_majority(quantized[row]) for row in range(height)]
    col_colors = [_majority(quantized[:, col]) for col in range(width)]
    rule = _rule_color(row_colors, col_colors)
    if rule is None:
        return None
    rows = _square_count([color == rule for color in row_colors])
    cols = _square_count([color == rule for color in col_colors])
    if rows is None or cols is None or rows < 2 or cols < 2 or rows > 64 or cols > 64:
        return None
    return rows, cols


def read_chart(image: str | Path | bytes | np.ndarray) -> Chart | None:
    """The color grid of a chart picture, or None when it is not a chart."""
    size = chart_size(image)
    if size is None:
        return None
    try:
        return chart_from_image(image, size[0], size[1])
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    """Print a chart's color grid from an image path, rows, and columns."""
    parser = argparse.ArgumentParser(description="Turn a knitting chart image into a color grid.")
    parser.add_argument("image_path")
    parser.add_argument("num_rows", type=int)
    parser.add_argument("num_cols", type=int)
    parser.add_argument("--max-k", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        chart = chart_from_image(args.image_path, args.num_rows, args.num_cols, args.max_k)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    for row in chart.grid.tolist():
        print(" ".join(str(value) for value in row))
    print()
    for index in sorted(chart.colors):
        print(f"{index} {chart.colors[index]}")
    return 0


def _count(value: int, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(message)
    return value


def _load_rgb(image: str | Path | bytes | np.ndarray) -> np.ndarray:
    if isinstance(image, np.ndarray):
        if image.ndim != 3 or image.shape[2] < 3 or image.shape[0] < 1 or image.shape[1] < 1:
            raise ValueError(MSG_IMAGE)
        rgb = image[:, :, :3]
        if rgb.dtype != np.uint8:
            rgb = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
        return np.ascontiguousarray(rgb)
    if isinstance(image, (str, Path)):
        try:
            data = Path(image).read_bytes()
        except OSError as error:
            raise ValueError(MSG_IMAGE) from error
    elif isinstance(image, bytes):
        data = image
    else:
        raise ValueError(MSG_IMAGE)
    if not data:
        raise ValueError(MSG_IMAGE)
    try:
        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as error:
        raise ValueError(MSG_IMAGE) from error
    if decoded is None or decoded.size == 0:
        raise ValueError(MSG_IMAGE)
    return cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)


def _cell_colors(image: np.ndarray, num_rows: int, num_cols: int) -> np.ndarray:
    height, width = image.shape[:2]
    if num_rows > height or num_cols > width:
        raise ValueError(MSG_SMALL)
    samples = np.empty((num_rows, num_cols, 3), dtype=np.uint8)
    for row in range(num_rows):
        y0 = row * height // num_rows
        y1 = (row + 1) * height // num_rows
        for col in range(num_cols):
            x0 = col * width // num_cols
            x1 = (col + 1) * width // num_cols
            ys, ye = _center(y0, y1)
            xs, xe = _center(x0, x1)
            patch = image[ys:ye, xs:xe]
            if patch.size == 0:
                raise ValueError(MSG_SMALL)
            median = np.median(patch.reshape(-1, 3), axis=0)
            samples[row, col] = np.clip(np.rint(median), 0, 255).astype(np.uint8)
    return samples


def _majority(line: np.ndarray) -> tuple[int, int, int] | None:
    colors, counts = np.unique(line.reshape(-1, 3), axis=0, return_counts=True)
    index = int(counts.argmax())
    if counts[index] < round(0.95 * int(counts.sum())):
        return None
    color = colors[index]
    return int(color[0]), int(color[1]), int(color[2])


def _rule_color(
    rows: list[tuple[int, int, int] | None],
    cols: list[tuple[int, int, int] | None],
) -> tuple[int, int, int] | None:
    hits: dict[tuple[int, int, int], list[int]] = {}
    for axis, colors in ((0, rows), (1, cols)):
        for color in colors:
            if color is None:
                continue
            hits.setdefault(color, [0, 0])[axis] += 1
    best: tuple[int, int, int] | None = None
    best_count = 0
    for color, (row_hits, col_hits) in hits.items():
        if row_hits < 2 or col_hits < 2:
            continue
        total = row_hits + col_hits
        if total > best_count:
            best = color
            best_count = total
    return best


def _square_count(is_rule: list[bool]) -> int | None:
    lengths: list[int] = []
    start: int | None = None
    for index, rule in enumerate(is_rule):
        if not rule and start is None:
            start = index
        elif rule and start is not None:
            lengths.append(index - start)
            start = None
    if start is not None:
        lengths.append(len(is_rule) - start)
    if not lengths:
        return None
    median = float(np.median(lengths))
    if median < 2:
        return None
    kept = [length for length in lengths if length >= median * 0.5]
    if len(kept) < 2 or max(kept) > median * 2.5:
        return None
    return len(kept)


def _center(start: int, end: int) -> tuple[int, int]:
    inset = (end - start) // 3
    if inset <= 0:
        mid = (start + end) // 2
        return mid, min(end, mid + 1)
    return start + inset, end - inset


def _palette(samples: np.ndarray, max_k: int) -> np.ndarray:
    quantized = _quantize(samples)
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    if len(colors) == 1:
        return colors
    total = int(counts.sum())
    keep = colors[counts >= total * NOISE]
    if 2 <= len(keep) <= max_k:
        return _sort_colors(keep)
    return _kmeans_palette(samples, max_k)


def _quantize(pixels: np.ndarray) -> np.ndarray:
    binned = np.rint(pixels.astype(np.float32) / BIN) * BIN
    return np.clip(binned, 0, 255).astype(np.uint8)


def _kmeans_palette(samples: np.ndarray, max_k: int) -> np.ndarray:
    points = samples.astype(np.float32)
    scored = _representative(points)
    distinct = np.unique(np.clip(np.rint(scored), 0, 255).astype(np.uint8), axis=0)
    if len(distinct) < 2:
        return distinct
    upper = min(max_k, len(scored) - 1)
    if upper < 2:
        center = np.clip(np.rint(points.mean(axis=0, keepdims=True)), 0, 255).astype(np.uint8)
        return center
    best_k = 0
    best_score = -np.inf
    for k in range(2, upper + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(scored)
        if len(np.unique(labels)) < 2:
            continue
        try:
            score = float(silhouette_score(scored, labels))
        except ValueError:
            continue
        if score > best_score:
            best_score = score
            best_k = k
    if best_k < 2:
        center = np.clip(np.rint(points.mean(axis=0, keepdims=True)), 0, 255).astype(np.uint8)
        return center
    model = KMeans(n_clusters=best_k, n_init=10, random_state=0).fit(points)
    rounded = np.clip(np.rint(model.cluster_centers_), 0, 255).astype(np.uint8)
    return _sort_colors(np.unique(rounded, axis=0))


def _representative(points: np.ndarray) -> np.ndarray:
    if len(points) <= SAMPLE_LIMIT:
        return points
    step = max(1, len(points) // SAMPLE_LIMIT)
    return points[::step][:SAMPLE_LIMIT]


def _sort_colors(colors: np.ndarray) -> np.ndarray:
    order = np.lexsort((colors[:, 2], colors[:, 1], colors[:, 0]))
    return colors[order]


def _indices(samples: np.ndarray, palette: np.ndarray) -> np.ndarray:
    diff = samples.astype(np.int32)[:, :, None, :] - palette.astype(np.int32)[None, None, :, :]
    distance = np.sum(diff * diff, axis=3)
    return distance.argmin(axis=2).astype(np.int64)


def _hex(color: np.ndarray) -> str:
    red, green, blue = (int(channel) for channel in color)
    return f"#{red:02X}{green:02X}{blue:02X}"


if __name__ == "__main__":
    sys.exit(main())
