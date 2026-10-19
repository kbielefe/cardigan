"""Ask the model to read a frozen pattern. The key is read from .env."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from project import otel
from project.env import env_value
from project.model import (
    COUNTERS,
    ENDS,
    KINDS,
    METHODS,
    OPEN_POINTS,
    ROLES,
    SCOPES,
    SETTINGS,
    SHAPES,
    SIDES,
    YARN_PLACES,
)
from project.parse import ParseFailure

URL = "https://api.x.ai/v1/chat/completions"
MODEL = "grok-4.7"
TIMEOUT = 900
_log = logging.getLogger("cardigan")

SYSTEM = """You turn one frozen knitting reading into pieces, sizes, and passes.

Use the shared actions only. Do not name a machine, a needle letter, or a lever.

A pass is one setup or one trip. Consecutive identical trips are one pass with a count. "Knit N rows" and "K N rows" are one trip. The count is the number for that size.

The first number in a group is the first size. The next sizes sit in parentheses, and the largest sit in square brackets. A parenthesis of words, such as (make 2), is the copies of that piece.

Each pass cites an exact span of the reading, copied unchanged. When the reading does not settle a point, leave it open. An extra needle with no side named uses open_point extra_needle_side and no side. A trip with no carriage end named has a null carriage end. Do not fill either in.

Seaming, blocking, construction, and how to wrap are not passes. Those pieces are parsed false and have no sizes. A section you cannot turn into passes is parsed false, with its heading. A parsed piece has a size for each size in the reading, and each size has its passes.
"""

OnDelta = Callable[[str], None]


def read_key(path: Path | None = None) -> str:
    value = env_value("XAI_API_KEY", path)
    if value:
        return value
    raise ParseFailure("The model key is not set.")


def complete(
    reading: str,
    *,
    key: str | None = None,
    post: Callable[[dict, str], dict] | None = None,
    on_delta: OnDelta | None = None,
) -> dict:
    token = read_key() if key is None else key
    if not token:
        raise ParseFailure("The model key is not set.")
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": reading},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "project", "strict": True, "schema": schema()},
        },
    }
    if post is None:
        body = _post(payload, token, on_delta)
    else:
        body = post(payload, token)
    try:
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ParseFailure("The reading did not parse.") from exc
    if type(parsed) is not dict:
        raise ParseFailure("The reading did not parse.")
    return parsed


def schema() -> dict:
    selection = _object(
        role=_enum(ROLES),
        method=_enum(METHODS),
        count=_nullable("integer"),
        every=_nullable("integer"),
        needles_between=_nullable("integer"),
        between_role=_nullable_enum(ROLES),
        needle=_nullable("integer"),
        side=_nullable_enum(SIDES),
    )
    setting = _object(name=_enum(SETTINGS), scope=_nullable_enum(SCOPES))
    shape = _object(
        name=_enum(SHAPES),
        count=_nullable("integer"),
        technique=_nullable_enum(("e-wrap",)),
    )
    yarn = _object(place=_enum(YARN_PLACES), name=_nullable("string"))
    counter = _object(kind=_enum(COUNTERS), value={"type": "integer", "minimum": 0})
    step = _object(
        kind=_enum(KINDS),
        count={"type": "integer", "minimum": 1},
        cite={"type": "string"},
        carriage_end=_nullable_enum(ENDS),
        row_counter={"anyOf": [{"type": "null"}, counter]},
        open_point=_nullable_enum(OPEN_POINTS),
        mark=_nullable("string"),
        selections={"type": "array", "items": selection},
        settings={"type": "array", "items": setting},
        shapes={"type": "array", "items": shape},
        yarns={"type": "array", "items": yarn},
    )
    repeat = _object(
        first={"type": "integer", "minimum": 0},
        last={"type": "integer", "minimum": 0},
        times={"type": "integer", "minimum": 2},
    )
    size = _object(
        name={"type": "string"},
        passes={"type": "array", "items": step},
        repeats={"type": "array", "items": repeat},
    )
    piece = _object(
        name={"type": "string"},
        copies={"type": "integer", "minimum": 1},
        parsed={"type": "boolean"},
        sizes={"type": "array", "items": size},
    )
    return _object(pieces={"type": "array", "items": piece})


def _post(payload: dict, key: str, on_delta: OnDelta | None = None) -> dict:
    outbound = {**payload, "stream": True}
    body = json.dumps(outbound)
    _log.debug("llm request %s", body)
    request = Request(
        URL,
        data=body.encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with otel.llm_request(MODEL, URL):
        try:
            with urlopen(request, timeout=TIMEOUT) as response:
                content = _read_stream(response, on_delta)
            _log.debug("llm response %s", content)
            return {"choices": [{"message": {"content": content}}]}
        except HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            _log.debug("llm HTTP %s response %s", exc.code, err_body)
            if exc.code in {401, 403}:
                raise ParseFailure("The model key was refused.") from None
            raise ParseFailure("The model refused the reading.") from None
        except (TimeoutError, URLError) as exc:
            _log.debug("llm transport error: %s", exc)
            raise ParseFailure("The model did not answer.") from None
        except json.JSONDecodeError as exc:
            _log.debug("llm JSON error: %s", exc)
            raise ParseFailure("The model did not answer.") from None


def _read_stream(response, on_delta: OnDelta | None) -> str:
    parts: list[str] = []
    for raw in response:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        try:
            delta = chunk["choices"][0]["delta"]
        except (KeyError, IndexError, TypeError):
            continue
        for key in ("reasoning_content", "content"):
            text = delta.get(key)
            if type(text) is str and text:
                if key == "content":
                    parts.append(text)
                if on_delta is not None:
                    on_delta(text)
    return "".join(parts)


def _enum(values: tuple[str, ...]) -> dict:
    return {"type": "string", "enum": list(values)}


def _nullable(kind: str) -> dict:
    return {"anyOf": [{"type": "null"}, {"type": kind}]}


def _nullable_enum(values: tuple[str, ...]) -> dict:
    return {"anyOf": [{"type": "null"}, _enum(values)]}


def _object(**properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
