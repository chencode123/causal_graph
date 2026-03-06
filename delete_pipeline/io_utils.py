from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def resolve_var_value(value: Any) -> str:
    if isinstance(value, Path):
        return read_text(value)
    return str(value)


def render_prompt(template: str, variables: Dict[str, Any]) -> str:
    materialized = {k: resolve_var_value(v) for k, v in variables.items()}
    try:
        return template.format(**materialized)
    except KeyError as exc:
        missing = str(exc)
        raise KeyError(
            f"Prompt template missing variable: {missing}. "
            f"Available vars: {sorted(materialized.keys())}"
        ) from exc


def extract_text_from_responses_body(body: Dict[str, Any]) -> str:
    if isinstance(body, dict) and isinstance(body.get("output_text"), str):
        return body["output_text"]

    output = body.get("output")
    if isinstance(output, list):
        parts: List[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for chunk in content:
                    if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                        parts.append(chunk["text"])
        if parts:
            return "\n".join(parts)

    return json.dumps(body, ensure_ascii=False, indent=2)


def truncate_text(content: str, limit: int = 50000) -> str:
    if len(content) <= limit:
        return content
    return content[:limit] + f"\n\n...[TRUNCATED {len(content) - limit} chars]..."


def save_step_input_snapshot(
    folder: Path,
    step_key: str,
    template: str,
    vars_dict: Dict[str, Any],
    prompt_text: str,
    messages: List[Dict[str, str]],
    truncate_limit: int = 50000,
) -> None:
    debug_dir = folder / "_debug_inputs"
    debug_dir.mkdir(parents=True, exist_ok=True)

    materialized = {k: resolve_var_value(v) for k, v in vars_dict.items()}
    materialized_trunc = {k: truncate_text(str(v), truncate_limit) for k, v in materialized.items()}

    write_text(
        debug_dir / f"{step_key}_vars_materialized.json",
        json.dumps(materialized_trunc, ensure_ascii=False, indent=2),
    )
    write_text(debug_dir / f"{step_key}_prompt_template.txt", truncate_text(template, truncate_limit))
    write_text(debug_dir / f"{step_key}_prompt_rendered.txt", truncate_text(prompt_text, truncate_limit))
    write_text(
        debug_dir / f"{step_key}_messages.json",
        json.dumps(messages, ensure_ascii=False, indent=2),
    )


def get_response_dir(folder: Path) -> Path:
    response_dir = folder / "response"
    response_dir.mkdir(parents=True, exist_ok=True)
    return response_dir
