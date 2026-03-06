# utils/input_normalization.py
from __future__ import annotations

from pathlib import Path
import json
from typing import Any

def normalize_input_var(v: Any) -> str:
    """
    Return a JSON literal string for embedding into prompt.

    - dict/list/tuple: pretty JSON (object/array)
    - Path or file-path str: read file; if file content is JSON, keep it as JSON;
      otherwise embed as JSON string.
    - plain str: JSON string
    - None: JSON null
    - other: JSON string of str(v)
    """
    if v is None:
        return "null"

    # Path object
    if isinstance(v, Path):
        if v.exists() and v.is_file():
            text = v.read_text(encoding="utf-8")
            return _text_to_json_literal(text)
        return json.dumps(str(v), ensure_ascii=False)

    # str that might be a file path
    if isinstance(v, str):
        p = Path(v)
        if p.exists() and p.is_file():
            text = p.read_text(encoding="utf-8")
            return _text_to_json_literal(text)
        return json.dumps(v, ensure_ascii=False)

    # structured -> JSON literal
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, ensure_ascii=False, indent=2)

    return json.dumps(str(v), ensure_ascii=False)


def _text_to_json_literal(text: str) -> str:
    """
    If text itself is valid JSON, keep it as JSON (pretty).
    Otherwise embed as JSON string.
    """
    s = text.strip()
    if not s:
        return json.dumps("", ensure_ascii=False)

    # try parse JSON
    try:
        obj = json.loads(s)
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        # not JSON -> embed as JSON string
        return json.dumps(text, ensure_ascii=False)
