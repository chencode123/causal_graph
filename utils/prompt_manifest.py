from __future__ import annotations

from pathlib import Path


PROMPT_TEMPLATE_SUFFIXES: tuple[str, ...] = (".txt", ".json")


def resolve_template_path(prompt_dir: Path, template_file: str) -> Path:
    candidate = prompt_dir / template_file
    if candidate.exists():
        return candidate

    if Path(template_file).suffix:
        return candidate

    for suffix in PROMPT_TEMPLATE_SUFFIXES:
        suffixed = prompt_dir / f"{template_file}{suffix}"
        if suffixed.exists():
            return suffixed

    return candidate
