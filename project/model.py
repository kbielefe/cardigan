"""A machine-independent project: pieces, sizes, and passes.

A pass uses the shared actions. It has no machine and no needle letter.
"""

from __future__ import annotations

from dataclasses import dataclass

ROLES = ("out_of_work", "working", "upper", "holding")
METHODS = (
    "stitch_count",
    "each_side",
    "extra",
    "every_nth",
    "needle_number",
    "side",
    "edge",
    "all",
)
SIDES = ("left", "right")
KINDS = ("setup", "trip")
ENDS = ("left", "right", "either")
COUNTERS = ("reset", "checkpoint", "target")
OPEN_POINTS = (
    "shaping_moment",
    "number_kind",
    "extra_needle_side",
    "row_or_trips",
    "carriage_end",
    "needle_letter",
    "unknown_counter",
    "chart_edge",
)
SETTINGS = ("plain", "slip", "hold", "knit_holding", "tuck", "intarsia")
SCOPES = ("left", "right", "both")
SHAPES = (
    "increase",
    "decrease",
    "transfer",
    "move",
    "short_row_wrap",
    "bind_off",
    "cast_on",
    "scrap_off",
)
YARN_PLACES = ("main", "plating", "unnamed", "rest")
SECTION_KINDS = (
    "piece",
    "method",
    "glossary",
    "gauge",
    "sizes",
    "yarn",
    "machine",
    "notes",
    "finishing",
    "page",
)


def _int(value: object, name: str, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _optional_int(value: object, name: str, minimum: int | None = None) -> int | None:
    if value is None:
        return None
    return _int(value, name, minimum)


def _choice(value: object, name: str, choices: tuple[str, ...]) -> str:
    if type(value) is not str or value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(choices)}")
    return value


def _optional_choice(value: object, name: str, choices: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    return _choice(value, name, choices)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be text")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _id(value: object, name: str) -> None:
    if value is not None:
        _int(value, name, 1)


def _tuple(value: object, name: str, kind: type) -> None:
    if type(value) is not tuple or any(type(item) is not kind for item in value):
        raise ValueError(f"{name} must be a tuple of {kind.__name__.lower()}s")


def _unused(method: str, obj: object, *names: str) -> None:
    for name in names:
        if getattr(obj, name) is not None:
            raise ValueError(f"{name} does not belong on {method}")


@dataclass(frozen=True)
class Selection:
    role: str
    method: str
    count: int | None = None
    every: int | None = None
    needles_between: int | None = None
    between_role: str | None = None
    needle: int | None = None
    side: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        _choice(self.role, "role", ROLES)
        _choice(self.method, "method", METHODS)
        _id(self.id, "selection id")
        if self.method == "stitch_count":
            _int(self.count, "count", 1)
            _unused(self.method, self, "every", "needles_between", "between_role", "needle", "side")
        elif self.method == "each_side":
            _int(self.count, "count", 1)
            _optional_choice(self.side, "side", SIDES)
            _unused(self.method, self, "every", "needles_between", "between_role", "needle")
        elif self.method == "extra":
            _int(self.count, "count", 1)
            _optional_choice(self.side, "side", SIDES)
            _unused(self.method, self, "every", "needles_between", "between_role", "needle")
        elif self.method == "every_nth":
            _int(self.every, "every", 2)
            if self.needles_between is None:
                _unused(self.method, self, "between_role")
            else:
                _int(self.needles_between, "needles between", 1)
                _choice(self.between_role, "between role", ROLES)
            _unused(self.method, self, "count", "needle", "side")
        elif self.method == "needle_number":
            _int(self.needle, "needle")
            _unused(self.method, self, "count", "every", "needles_between", "between_role", "side")
        elif self.method == "side":
            _choice(self.side, "side", SIDES)
            _unused(self.method, self, "count", "every", "needles_between", "between_role", "needle")
        elif self.method == "edge":
            _optional_int(self.count, "count", 1)
            _optional_choice(self.side, "side", SIDES)
            _unused(self.method, self, "every", "needles_between", "between_role", "needle")
        else:
            _unused(
                self.method,
                self,
                "count",
                "every",
                "needles_between",
                "between_role",
                "needle",
                "side",
            )


@dataclass(frozen=True)
class CarriageSetting:
    name: str
    scope: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        _choice(self.name, "carriage setting", SETTINGS)
        _optional_choice(self.scope, "scope", SCOPES)
        _id(self.id, "carriage setting id")


@dataclass(frozen=True)
class Shape:
    name: str
    count: int | None = None
    technique: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        _choice(self.name, "shape", SHAPES)
        _optional_int(self.count, "count", 1)
        _id(self.id, "shape id")
        if self.technique is not None and (self.name != "cast_on" or self.technique != "e-wrap"):
            raise ValueError("only an e-wrap cast-on names a technique")


@dataclass(frozen=True)
class Yarn:
    place: str
    name: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        _choice(self.place, "yarn", YARN_PLACES)
        _optional_text(self.name, "yarn name")
        _id(self.id, "yarn id")


@dataclass(frozen=True)
class RowCounter:
    kind: str
    value: int

    def __post_init__(self) -> None:
        _choice(self.kind, "row counter", COUNTERS)
        _int(self.value, "row counter", 0)


@dataclass(frozen=True)
class Repeat:
    first: int
    last: int
    times: int
    id: int | None = None

    def __post_init__(self) -> None:
        _int(self.first, "repeat start", 0)
        _int(self.last, "repeat end", 0)
        _int(self.times, "repeat", 2)
        _id(self.id, "repeat id")
        if self.last < self.first:
            raise ValueError("repeat ends before it starts")


@dataclass(frozen=True)
class Pass:
    kind: str
    cite_start: int
    cite_end: int
    count: int = 1
    carriage_end: str | None = None
    row_counter: RowCounter | None = None
    open_point: str | None = None
    selections: tuple[Selection, ...] = ()
    settings: tuple[CarriageSetting, ...] = ()
    shapes: tuple[Shape, ...] = ()
    yarns: tuple[Yarn, ...] = ()
    mark: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        _choice(self.kind, "kind", KINDS)
        _int(self.count, "count", 1)
        if self.kind == "setup" and self.count != 1:
            raise ValueError("a setup is one pass")
        _optional_choice(self.carriage_end, "carriage end", ENDS)
        if self.row_counter is not None and type(self.row_counter) is not RowCounter:
            raise ValueError("row counter must be a row counter")
        _optional_choice(self.open_point, "open point", OPEN_POINTS)
        _int(self.cite_start, "cite start", 0)
        _int(self.cite_end, "cite end", 0)
        if self.cite_end < self.cite_start:
            raise ValueError("citation ends before it starts")
        _tuple(self.selections, "selections", Selection)
        _tuple(self.settings, "settings", CarriageSetting)
        _tuple(self.shapes, "shapes", Shape)
        _tuple(self.yarns, "yarns", Yarn)
        _optional_text(self.mark, "mark")
        _id(self.id, "pass id")
        if self.open_point == "extra_needle_side" and any(item.side is not None for item in self.selections):
            raise ValueError("the extra needle's side is open")
        if self.open_point == "carriage_end" and self.carriage_end is not None:
            raise ValueError("the carriage end is open")


@dataclass(frozen=True)
class Size:
    name: str
    passes: tuple[Pass, ...] = ()
    repeats: tuple[Repeat, ...] = ()
    id: int | None = None

    def __post_init__(self) -> None:
        _text(self.name, "size")
        _tuple(self.passes, "passes", Pass)
        _tuple(self.repeats, "repeats", Repeat)
        _id(self.id, "size id")
        spans = []
        for repeat in self.repeats:
            if repeat.last >= len(self.passes):
                raise ValueError("repeat is outside the passes")
            spans.append((repeat.first, repeat.last))
        spans.sort()
        for (start, end), (next_start, _) in zip(spans, spans[1:]):
            if next_start <= end:
                raise ValueError("repeats overlap")


@dataclass(frozen=True)
class Abbreviation:
    abbr: str
    expansion: str
    id: int | None = None

    def __post_init__(self) -> None:
        _text(self.abbr, "abbreviation")
        _text(self.expansion, "expansion")
        _id(self.id, "abbreviation id")


@dataclass(frozen=True)
class Section:
    """One verbatim span of the pattern. Joined in order, the sections are the reading.

    A reading is absent until this section has been parsed. Kind, procedure, and the
    facts below are that reading.
    """

    text: str
    id: int | None = None
    kind: str | None = None
    heading: str | None = None
    copies: int | None = None
    procedure: bool | None = None
    size_names: tuple[str, ...] = ()
    glossary: tuple[Abbreviation, ...] = ()

    def __post_init__(self) -> None:
        if type(self.text) is not str or self.text == "":
            raise ValueError("section must be text")
        _id(self.id, "section id")
        _tuple(self.size_names, "size names", str)
        if any(not name.strip() for name in self.size_names):
            raise ValueError("size name must be text")
        _tuple(self.glossary, "glossary", Abbreviation)
        if self.kind is None:
            if (
                self.heading is not None
                or self.copies is not None
                or self.procedure is not None
                or self.size_names
                or self.glossary
            ):
                raise ValueError("an unread section has no reading")
            return
        _choice(self.kind, "section kind", SECTION_KINDS)
        _optional_text(self.heading, "heading")
        if type(self.procedure) is not bool:
            raise ValueError("procedure must be true or false")
        if self.kind == "piece":
            _optional_int(self.copies, "copies", 1)
        elif self.copies is not None:
            raise ValueError("copies belong on a piece")
        if self.kind != "sizes" and self.size_names:
            raise ValueError("size names belong on a sizes section")
        if self.kind != "glossary" and self.glossary:
            raise ValueError("a glossary belongs on a glossary section")


@dataclass(frozen=True)
class Piece:
    name: str
    sizes: tuple[Size, ...] = ()
    copies: int = 1
    parsed: bool = True
    id: int | None = None

    def __post_init__(self) -> None:
        _text(self.name, "piece")
        _tuple(self.sizes, "sizes", Size)
        _int(self.copies, "copies", 1)
        if type(self.parsed) is not bool:
            raise ValueError("parsed must be true or false")
        if not self.parsed and self.sizes:
            raise ValueError("an unparsed piece has no sizes")
        _id(self.id, "piece id")


@dataclass(frozen=True)
class Project:
    reading: str
    pieces: tuple[Piece, ...] = ()
    sections: tuple[Section, ...] = ()
    name: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if type(self.reading) is not str:
            raise ValueError("reading must be text")
        _optional_text(self.name, "project name")
        _tuple(self.pieces, "pieces", Piece)
        _tuple(self.sections, "sections", Section)
        _id(self.id, "project id")
        limit = len(self.reading)
        for piece in self.pieces:
            for size in piece.sizes:
                for step in size.passes:
                    if step.cite_end > limit:
                        raise ValueError("citation is outside the reading")
