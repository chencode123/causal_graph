from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Iterable
import re

# Robust arrow parsing: supports -> and common unicode arrows.
_ARROW_RE = re.compile(r"^\s*(.*?)\s*->\s*(.*?)\s*$")

import re

_LEADING_ENUM_RE = re.compile(
    r"""
    ^\s*                # leading whitespace
    (?:                 # non-capturing group
        \d+\s*[.)]      # 1.   or 1)
      | \(\d+\)         # (1)
      | \d+             # 1
    )
    \s+                 # at least one space
    """,
    re.VERBOSE,
)

def _normalize_line(s: str) -> str:
    if s is None:
        return ""

    # normalize invisible spaces
    s = (s.replace("\u00A0", " ")
           .replace("\u2009", " ")
           .replace("\u202F", " ")
           .replace("\u200B", "")
           .replace("\ufeff", ""))

    # normalize arrows
    s = (s.replace("→", "->")
           .replace("⇒", "->")
           .replace("⟶", "->")
           .replace("➜", "->")
           .replace("➔", "->"))

    # normalize dash-like characters
    s = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212\uFE63\uFF0D]", "-", s)

    s = s.strip()

    # 🔹 NEW: remove leading enumeration like "1. ", "2) ", "(3) "
    s = _LEADING_ENUM_RE.sub("", s)

    return s

@dataclass(frozen=True)
class Edge:
    src: str
    dst: str

    def as_text(self) -> str:
        return f"{self.src} -> {self.dst}"


def extract_edges(combined_text: str, *, dedupe: bool = False) -> List[Edge]:
    """
    Extract all 'A -> B' lines from COMBINED_TEXT.
    Keeps original wording (except whitespace normalization around arrow).
    """
    if not combined_text:
        return []

    edges: List[Edge] = []
    seen = set()

    for raw in combined_text.splitlines():
        line = _normalize_line(raw)
        if not line:
            continue

        m = _ARROW_RE.match(line)
        if not m:
            continue

        a = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".").strip()
        b = re.sub(r"\s+", " ", m.group(2)).strip().rstrip(".").strip()

        if not a or not b:
            continue

        e = Edge(a, b)
        if dedupe:
            key = e.as_text()
            if key in seen:
                continue
            seen.add(key)
        edges.append(e)

    return edges


def format_edges(edges: Iterable[Edge]) -> str:
    """Format edges as 'A -> B' lines."""
    return "\n".join(e.as_text() for e in edges)
