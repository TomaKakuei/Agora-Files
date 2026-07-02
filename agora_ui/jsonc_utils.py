"""Helpers for loading and writing JSONC-like files.

Supported features:
- `//` line comments
- `/* ... */` block comments
- trailing commas before `}` or `]`
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def strip_jsonc_comments(text: str) -> str:
    chars: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    in_line_comment = False
    in_block_comment = False
    escape = False

    while index < length:
        char = text[index]
        next_char = text[index + 1] if index + 1 < length else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                chars.append(char)
            index += 1
            continue

        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        if in_string:
            chars.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue

        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue

        chars.append(char)
        if char == '"':
            in_string = True
        index += 1

    return "".join(chars)


def strip_trailing_commas(text: str) -> str:
    chars: list[str] = []
    length = len(text)
    index = 0
    in_string = False
    escape = False

    while index < length:
        char = text[index]

        if in_string:
            chars.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            chars.append(char)
            index += 1
            continue

        if char == ",":
            lookahead = index + 1
            while lookahead < length and text[lookahead] in {" ", "\t", "\r", "\n"}:
                lookahead += 1
            if lookahead < length and text[lookahead] in {"]", "}"}:
                index += 1
                continue

        chars.append(char)
        index += 1

    return "".join(chars)


def normalize_jsonc(text: str) -> str:
    return strip_trailing_commas(strip_jsonc_comments(text))


def loads_jsonc(text: str) -> Any:
    return json.loads(normalize_jsonc(text))


def load_jsonc_path(path: str | Path) -> Any:
    resolved = Path(path).expanduser().resolve()
    return loads_jsonc(resolved.read_text(encoding="utf-8"))


def dump_json(path: str | Path, payload: Any) -> Path:
    resolved = Path(path).expanduser().resolve()
    _ensure_parent(resolved)
    resolved.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return resolved


def dump_jsonc(
    path: str | Path,
    payload: Any,
    *,
    comment_lines: list[str] | None = None,
) -> Path:
    resolved = Path(path).expanduser().resolve()
    _ensure_parent(resolved)
    prefix = ""
    if comment_lines:
        prefix = "".join(f"// {line}\n" for line in comment_lines)
    resolved.write_text(
        prefix + json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return resolved
